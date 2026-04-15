import torch
from torch.utils.data import Dataset
import pandas as pd
from PIL import Image
from typing import Tuple, Optional
import torchvision.transforms as transforms

class HAM10000Dataset(Dataset):
    """Custom PyTorch Dataset for HAM10000 skin lesions."""
    
    def __init__(self, df: pd.DataFrame, transform: Optional[transforms.Compose] = None):
        self.df = df.reset_index(drop=True)
        self.transform = transform
        
    def __len__(self) -> int:
        return len(self.df)
    
    def __getitem__(self, idx: int) -> Tuple[torch.Tensor, torch.Tensor]:
        img_path = self.df.loc[idx, 'path']
        image = Image.open(img_path).convert('RGB')
        label = torch.tensor(self.df.loc[idx, 'target'], dtype=torch.long)
        
        if self.transform:
            image = self.transform(image)
            
        return image, label