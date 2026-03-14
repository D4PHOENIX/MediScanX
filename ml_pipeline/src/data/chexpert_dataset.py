import os
import cv2
import torch
import numpy as np
import pandas as pd
from PIL import Image
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms

class CheXpertDataset(Dataset):
    """
    A custom PyTorch Dataset implementation for CheXpert database.
    
    This class handles the parsing of the clinical annotations in CSV, loads the corresponding high-resolution
    X-ray images from the disk using OpenCV, applies the defined preprocessing transforms, and
    extracts the multi-label pathology vectors.

    Attributes:
        annotations (pd.DataFrame): The parsed CSV data containing paths and clinical labels.
        root_dir(str): The base directory path where the image dataset is stored.
        transform(callable, optional): A pytorch transform to apply to the images.
    """
    def __init__(self, csv_file: str, root_dir: str, transform: callable=None):
        """
        Initializes the CheXpert Dataset.

        Args:
            csv_file (str): Path to the train.csv or valid.csv file.
            root_dir (str): Directory containing the CheXpert image folders.
            transform (callable, optional): Optional transform to be applied on a sample. Defaults to None.
        """
        super().__init__()
        # Load the CSV. CheXpert labels sometimes contain -1 (uncertain).
        # U-Ones Policy: Map -1(uncertain) to 1 (positive) for triage safety.
        self.annotations = pd.read_csv(csv_file)
        self.annotations = self.annotations.fillna(0)
        self.annotations = self.annotations.replace(-1, 1)
        
        self.root_dir = root_dir
        self.transform = transform
        
    def __len__(self) -> int:
        """Returns the total number of patient scans in the dataset."""
        return len(self.annotations)
    
    def __getitem__(self, idx: int) -> tuple:
        """
        Retrieves a single medical image and its corresponding pathology labels.

        Args:
            idx (int): The index of the item to retrieve.

        Returns:
            tuple: A tuple containing (image_tensor, label_tensor).
        """
        if torch.is_tensor(idx):
            idx = idx.tolist()
        
        # The CheXpert 'Path column contains the relative path
        img_name = os.path.join(self.root_dir, self.annotations.iloc[idx]['Path'])
        
        # Load the image strictly in grayscale
        image = cv2.imread(img_name, cv2.IMREAD_GRAYSCALE)
        
        if image is None:
            raise FileNotFoundError(f"OpenCV could not read the image at {img_name}")

        # Extract the 14 pathology labels (columns 5 to 18 in CheXpert)
        labels = self.annotations.iloc[idx, 5:19].values.astype(np.float32)
        
        if self.transform:
            image = self.transform(image)
            
        labels = torch.tensor(labels)
        
        return image, labels