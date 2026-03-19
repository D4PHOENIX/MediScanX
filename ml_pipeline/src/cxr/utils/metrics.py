"""
Statistical utilities for CXR dataset balancing.
Dynamically calculates positive weights to counteract clinical class imbalances.
"""
import torch
import numpy as np
import pandas as pd

class ClassWeightCalculator:
    """
    Utility class for calculating positive loss weights in imbalanced clinical datasets.
    """
    
    @staticmethod
    def compute_pos_weights(df: pd.DataFrame, num_classes: int = 14) -> torch.Tensor:
        """
        Calculates the ratio of negative to positive samples for each diagnostic class.
        
        This creates a weight vector optimized for `BCEWithLogitsLoss(pos_weight=...)` to scale 
        the gradient of minority positive classes during back propagation.
        
        Args:
            df (pd.DataFrame): The raw training dataframe containing clinical annotations.
            num_classes (int): Total number of pathology labels to evaluate. Defaults to 14.
            
        Returns:
            torch.Tensor: A 1D tensor of strictly typed positive weights.
        """
        # Clean the dataframe dynamically: fill NaNs with 0, apply U-Ones policy (-1 to 1)
        df_clean = df.fillna(0).replace(-1, 1)
        
        # Extract the label matrix (CheXpert pathology labels strictly start at column index 5)
        labels = df_clean.iloc[:, 5:5 + num_classes].values
        
        # Calculate class distributions
        pos_counts = np.sum(labels == 1, axis=0)
        neg_counts = np.sum(labels == 0, axis=0)
        
        # Add a small epsilon to the denominator to prevent division by zero
        pos_weights = neg_counts / (pos_counts + 1e-7)
        
        return torch.tensor(pos_weights, dtype=torch.float32)