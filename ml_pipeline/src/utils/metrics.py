import torch
import numpy as np
import pandas as pd
# Define the standard CheXpert labels in order
CHEXPERT_LABELS = [
    "No Finding", "Enlarged Cardiomediastinum", "Cardiomegaly", "Lung Opacity",
    "Lung Lesion", "Edema", "Consolidation", "Pneumonia", "Atelectasis", 
    "Pneumothorax", "Pleural Effusion", "Pleural Other", "Fracture", "Support Devices"
]

# Map child indices to their parent disease index.
# CheXpert Label Indices (Matching the Dataset class order):
# 0: No Finding, 1: Enlarged Cardiomediastinum, 2: Cardiomegaly
# 3: Lung Opacity, 4: Lung Lesion, 5: Edema, 6: Consolidation
# 7: Pneumonia, 8: Atelectasis, 9: Pneumothorax, 10: Pleural Effusion
# 11: Pleural Other, 12: Fracture, 13: Support Devices

# Define the Clinical Taxonomy (Parent Index -> List of Child Indices)
# Based on the CheXpert label indices:
# 1: 'Enlarged Cardiomediastinum' -> 2: 'Cardiomegaly'
# 3: 'Lung Opacity' -> 4: 'Lung Lesion', 5: 'Edema', 6: 'Consolidation', 8: 'Atelectasis
# 6: 'Consolidation -> 7: 'Pneumonia'

# List of Tuples (parent_index, child_index)
# Enforces multi-level hierarchical rules
HIERARCHY_PAIRS = [
    (1, 2),
    (3, 4),
    (3, 5),
    (3, 6),
    (3, 8),
    (6, 7)
]

class ClassWeightCalculator:
    """Utility class to calculate positive weights for imbalanced datasets."""
    
    @staticmethod
    def compute_pos_weights(df: pd.DataFrame, num_classes: int = 14) -> torch.Tensor:
        """
        Calculates the ratio of negative to positive samples for each class.
        
        Args:
            df (pd.DataFrame): The training dataframe.
            num_classes (int): Total number of pathology labels.
            
        Returns:
            torch.Tensor: A 1D tensor of positive weights for BCEWithLogitsLoss.
        """
        # Clean the dataframe dynamically: fill NaNs with 0, and apply U-Ones policy (-1 to 1)
        df_clean = df.fillna(0).replace(-1, 1)
        
        # Extract the label matrix (assuming CheXpert labels start at column index 5)
        labels = df_clean.iloc[:, 5:5+num_classes].values
        
        pos_counts = np.sum(labels == 1, axis=0)
        neg_counts = np.sum(labels == 0, axis=0)
        
        # Add a small epsilon to prevent division by zero
        pos_weights = neg_counts / (pos_counts + 1e-7)
        return torch.tensor(pos_weights, dtype=torch.float32)
