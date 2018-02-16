import webvision.config as wvc_config
import torch.utils.data as data
from PIL import Image
import logging, os

_logger = logging.getLogger(__name__)


class WebVision(data.Dataset):
    def __init__(self, split='train', transform=None):
        db_info = wvc_config.LoadInfo()
        self.split = split
        self.img_ids = db_info[db_info.type == split].image_id.tolist()
        self.img_files = db_info[db_info.type == split].image_path.tolist()
        self.img_labels = db_info[db_info.type == split].label.tolist()
        self.transform = transform
        assert len(self.img_ids) == len(self.img_files)
        assert len(self.img_ids) == len(self.img_labels)
        _logger.info("Webvision dataset read with {} images".format(len(self.img_ids)))

    def __getitem__(self, index):
        img = Image.open(self.img_files[index])
        label = self.img_labels[index]
        if self.transform is not None:
            img = self.transform(img)
        return img, label

    def __len__(self):
        return len(self.img_ids)
