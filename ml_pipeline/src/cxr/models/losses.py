"""
Custom PyTorch loss functions for CXR diagnostics.
Includes hierarchical constraint penalties (HBCELoss) to enforce anatomically logical predictions.
"""
import torch.nn as nn
import torch.nn.functional as F

class HBCELoss(nn.Module):
    """
    Hierarchical Binary Cross-Entropy Loss.
    
    Attributes:
        pos_weight (torch.Tensor): Weights to counter class imbalance.
        hierarchy_pairs (list): List of (parent_idx, child_idx) tuples.
        penalty_weight (float): Multiplier for the hierarchical violation penalty.
    """
    
    def __init__(self, pos_weight: torch.Tensor, hierarchy_pairs: list, penalty_weight: float = 1.0):
        super(HBCELoss, self).__init__()
        self.pos_weight = pos_weight
        self.hierarchy_pairs = hierarchy_pairs
        self.penalty_weight = penalty_weight

    def forward(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        """
        Calculates the penalized loss using the cascading taxonomy map.
        """
        # Label Smoothing: 1.0 -> 0.95, 0.00 -> 0.05
        smoothed_targets = targets * 0.90 + 0.05
        
        # Standard Weighted Binary Cross Entropy
        bce_loss = F.binary_cross_entropy_with_logits(
            logits, targets, pos_weight=self.pos_weight, reduction='mean'
        )
        
        # Compute probabilities for the hierarchy check
        probs = torch.sigmoid(logits)
        
        # Calculate Hierarchical Penalties using the provided tuples
        penalty = torch.tensor(0.0, device=logits.device)
        
        for parent_idx, child_idx in self.hierarchy_pairs:
            # Violation occurs if P(Child) > P(Parent)
            # ReLU zeros out the tensor if P(Parent) is correctly higher than P(Child)
            violation = F.relu(probs[:, child_idx] - probs[:, parent_idx])
            penalty += torch.mean(violation)
            
        # Total Loss computation
        total_loss = bce_loss + (self.penalty_weight * penalty)
        return total_loss