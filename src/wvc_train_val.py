from torchvision import transforms
from torch.utils.data import dataloader
from torch.utils.data.sampler import WeightedRandomSampler
from torch.cuda import device_count
import torch
import wvc_data, wvc_model, wvc_utils
import logging, os
from tensorboard_logger import tensorboard_logger as tb_log


_logger = logging.getLogger(__name__)


def main(model_name, output_dir, batch_size=256, num_epochs=100, valid_int=1, checkpoint=None, num_workers=5, kwargs_str=None):
    # Data loading
    _logger.info("Reading WebVision Dataset")
    normalize = transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
    train_db = wvc_data.WebVision('train', transform=transforms.Compose([transforms.RandomCrop(224),
                                                                         transforms.RandomHorizontalFlip(),
                                                                         transforms.ToTensor(), normalize]))
    balanced_sampler = WeightedRandomSampler(train_db.sample_weight, train_db.sample_weight.size, replacement=False)
    train_data_loader = dataloader.DataLoader(train_db, batch_size=batch_size, sampler=balanced_sampler,
                                              num_workers=num_workers, pin_memory=True)

    val_db = wvc_data.WebVision('val', transform=transforms.Compose([transforms.CenterCrop(224),
                                                                     transforms.ToTensor(), normalize]))
    val_data_loader = dataloader.DataLoader(val_db, batch_size=batch_size, num_workers=num_workers, pin_memory=True)

    # Model building
    _logger.info("Building Model: {}".format(model_name))
    kwargs_dic = wvc_utils.get_kwargs_dic(kwargs_str)
    _logger.info("Arguments: {}".format(kwargs_dic))
    model = wvc_model.model_factory(model_name, kwargs_dic)
    _logger.info("Running model with {} GPUS and {} data workers".format(device_count(), num_workers))
    model = torch.nn.DataParallel(model).cuda()

    # Objective and Optimizer
    _logger.info("Setting up loss function and optimizer")
    criterion = torch.nn.CrossEntropyLoss().cuda()
    optimizer = torch.optim.Adam(model.parameters(), lr=float(kwargs_dic.get("lr", 1e-1)),
                                 weight_decay=float(kwargs_dic.get("weight_decay", 1e-4)))

    # Optionally resume from a checkpoint
    if checkpoint is not None:
        _logger.info("Resume training from {}".format(checkpoint))
        checkpoint = torch.load(checkpoint)
        start_epoch = checkpoint['epoch'] - 1
        best_acc5 = checkpoint['best_acc5']
        model.load_state_dict(checkpoint['state_dict'])
        optimizer.load_state_dict(checkpoint['optimizer'])
    else:
        start_epoch, best_acc5 = 0, 0.0

    # Training and Validation loop
    _logger.info("Training...")
    tb_logger = tb_log.Logger(output_dir)
    for epoch in range(start_epoch, num_epochs):
        # train for one epoch
        tr_loss, tr_acc1, tr_acc5 = wvc_model.train(train_data_loader, model, criterion, optimizer, epoch)
        _logger.info("Epoch Train {}/{}: tr_loss={:.3f}, tr_acc1={:.3f}, tr_acc5={:.3f}"
                     .format(epoch + 1, num_epochs, tr_loss, tr_acc1, tr_acc5))
        tb_logger.log_value('tr_loss', tr_loss, epoch+1); tb_logger.log_value('tr_acc1', tr_acc1, epoch+1)
        tb_logger.log_value('tr_acc5', tr_acc5, epoch+1)

        # Validation
        if (epoch + 1) % valid_int == 0:
            _logger.info("Validating...")
            val_loss, val_acc1, val_acc5 = wvc_model.validate(val_data_loader, model, criterion, epoch)
            _logger.info("Epoch Validation {}/{}: val_loss={:.3f}, val_acc1={:.3f}, val_acc5={:.3f}"
                         .format(epoch+1, num_epochs, val_loss, val_acc1, val_acc5))
            tb_logger.log_value('val_loss', val_loss, epoch+1); tb_logger.log_value('val_acc1', val_acc1, epoch+1)
            tb_logger.log_value('val_acc5', val_acc5, epoch+1)

            # save checkpoint
            model_ckpt_name = 'checkpoint.pth.tar'
            _logger.info("Save model checkpoint to {}".format(os.path.join(output_dir, model_ckpt_name)))
            is_best = val_acc5 > best_acc5
            best_acc5 = max(val_acc5, best_acc5)
            wvc_model.save_checkpoint({
                'epoch': epoch + 1,
                'state_dict': model.state_dict(),
                'optimizer': optimizer.state_dict(),
                'best_acc5': best_acc5}, is_best, output_dir, model_ckpt_name)


if __name__ == '__main__':
    import argparse
    from datetime import datetime

    parser = argparse.ArgumentParser(description="Training and Validation CNN Model.",
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('model_name', type=str, choices=wvc_model.MODELS, help='Name of the CNN architecture.')
    parser.add_argument('output_dir', type=str, help='Path to the output directory.')
    parser.add_argument('-batch_size', type=int, default=256, help='Batch size.')
    parser.add_argument('-num_epochs', type=int, default=100, help='Number of epochs.')
    parser.add_argument('-valid_int', type=int, default=1, help='Number epochs between evaluations.')
    parser.add_argument('-ckp_file', type=str, default=None, help='Resume from checkpoint file.')
    parser.add_argument('-gpu_str', type=str, default="0", help='Set CUDA_VISIBLE_DEVICES variable.')
    parser.add_argument('-num_workers', type=int, default=5, help='Number of preprocessing workers.')
    parser.add_argument('-kwargs_str', type=str, default=None, help="Hyper parameters as string of key value, e.g., k1=v1; k2=v2; ...")
    args = parser.parse_args()

    os.environ['CUDA_VISIBLE_DEVICES'] = args.gpu_str
    log_file = os.path.join(args.output_dir, "train_val_{}.log".format(datetime.now().strftime("%Y%m%d-%H%M%S")))
    wvc_utils.init_logging(log_file)
    _logger.info("Training and Validation CNN Model Tool: {}".format(args))
    main(args.model_name, args.output_dir, args.batch_size, args.num_epochs, args.valid_int, args.ckp_file,
         args.num_workers, args.kwargs_str)
