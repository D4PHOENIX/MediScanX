"""
Custom PyTorch Dataset implementation for the CheXpert medical imaging database.
It handles CSV parsing, strict grayscale OpenCV I/O, label extraction, preprocessing
through transforms and clinical triage policies (U-Ones).
"""
import os
import torch
import cv2
import numpy as np
import pandas as pd
from typing import Optional, Callable
from torch.utils.data import Dataset

class CheXpertDataset(Dataset):
    """
    A custom PyTorch Dataset implementation for the CheXpert database.
    
    This class handles the parsing of clinical annotations in CSV format, loads the corresponding 
    high-resolution X-ray images from disk using OpenCV, applies defined preprocessing transforms, 
    and extracts the multi-label pathology vectors.

    Attributes:
        annotations (pd.DataFrame): The parsed CSV data containing paths and clinical labels.
        root_dir (str): The base directory path where the image dataset is stored.
        transform (Callable, optional): A PyTorch transform to apply to the images.
    """
    
    def __init__(self, csv_file: str, root_dir: str, transform: Optional[Callable] = None) -> None:
        """
        Initializes the CheXpert Dataset.

        Args:
            csv_file (str): Path to the train.csv or valid.csv file.
            root_dir (str): Directory containing the CheXpert image folders.
            transform (Callable, optional): Optional transform applied to a sample.
        """
        super().__init__()
        
        # Load the CSV. CheXpert labels sometimes contain -1 (uncertain).
        # U-Ones Policy: Map -1 (uncertain) to 1 (positive) for triage safety.
        self.annotations = pd.read_csv(csv_file)
        self.annotations = self.annotations.fillna(0)
        self.annotations = self.annotations.replace(-1, 1)
        
        self.root_dir = root_dir
        self.transform = transform
        
    def __len__(self) -> int:
        """Returns the total number of patient scans in the dataset."""
        return len(self.annotations)
    
    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        """
        Retrieves a single medical image and its corresponding pathology labels.

        Args:
            idx (int): The index of the item to retrieve.

        Returns:
            tuple[torch.Tensor, torch.Tensor]: A tuple containing the processed image tensor 
                                                and the multi-hot label tensor.

        Raises:
            FileNotFoundError: If the resolved image path does not exist on disk.
        """
        if torch.is_tensor(idx):
            idx = idx.tolist()
        
        # The CheXpert 'Path' column contains the relative path
        original_path = self.annotations.iloc[idx]['Path']
        cleaned_path = original_path.replace('CheXpert-v1.0-small/', '')
        img_path = os.path.join(self.root_dir, cleaned_path)
        
        # Load the image strictly in grayscale
        image = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
        
        if image is None:
            raise FileNotFoundError(f"OpenCV could not read the image at: {img_path}")

        # Extract the 14 pathology labels (columns 5 to 18 in CheXpert)
        labels = self.annotations.iloc[idx, 5:19].values.astype(np.float32)
        
        if self.transform:
            image = self.transform(image)
            
        label_tensor = torch.tensor(labels, dtype=torch.float32)
        
        return image, label_tensor