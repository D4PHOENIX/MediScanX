import torch.nn as nn
import torch.nn.functional as F

class HBCELoss(nn.Module):
    """
    Hierarchical Binary Cross-Entropy Loss.
    
    Enforces parent-child taxonomic relationships by applying a penalty when
    the predicted probability of a child exceeds its parent.
    
    Attributes:
        pos_weight (torch.Tensor): Weights to counter class imbalance.
        hierarchy_pairs (list): List of (parent_idx, child_idx) tuples.
        penalty_weight (float): Multiplier for the hierarchical violation penalty.
    """
    def __init__(self, pos_weight: torch.Tensor, hierarchy_pairs: list, penalty_weight: float=1.0):
        """
        Initializes the HBCELoss module.

        Args:
            pos_weight (torch.Tensor): Tensor of weights for the positive class.
            hierarchy_pairs (list): Clinical taxonomy defined as [(parent, child), ...]
            penalty_weight (float, optional): Scaling factor for the penalty term. Defaults to 1.0.
        """
        super(HBCELoss, self).__init__()
        self.pos_weight = pos_weight
        self.hierarchy_pairs = hierarchy_pairs
        self.penalty_weight = penalty_weight
        
    def forward(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        """
        Calculates the total penalized loss.

        Args:
            logits (torch.Tensor): The raw output from the model (before sigmoid). Shape [B, 14]
            targets (torch.Tensor): The ground truth labels. Shape [B, 14]

        Returns:
            torch.Tensor: The scalar loss value combining BCE and the hierarchical penalty.
        """
        # Standard Weighted Binary Cross Entropy
        bce_loss = F.binary_cross_entropy_with_logits(
            logits, targets, pos_weight=self.pos_weightm, reduction='mean'
        )
        
        # Compute probabilites for the hierarchy check
        probs = torch.sigmoid(logits)
        
        # Calculate Hierarchical Penalties
        penalty = torch.Tensor(0.0, device=logits.device)
        
        for parent_idx, child_idx in self.hierarchy_pairs:
            # Violation occurs if P(child) > P(Parent)
            # P(Child) - P(Parent) yields a positive number if violated.
            # ReLU zeros out the result if the network correctly predicted P(Parent) >= P(Child)
            violation = F.relu(probs[:, child_idx] - probs[:, parent_idx])
            penalty += torch.mean(violation)
            
            # Total Loss Calculation
            total_loss = bce_loss + (self.penalty_weight * penalty)
            return total_loss