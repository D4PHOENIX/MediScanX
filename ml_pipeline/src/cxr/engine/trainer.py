"""
Execution engine for CXR model orchestration.
Manages optimization loops, GPU-accelerated augmentations, and clinical metric evaluation.
"""
import torch
import torch.nn as nn
import numpy as np
import wandb
from tqdm import tqdm
from sklearn.metrics import roc_auc_score, f1_score, precision_score, recall_score
from torch.utils.data import DataLoader
from torch.optim import Optimizer
from typing import Any
import torchvision.transforms.v2 as v2
from src.cxr.config import CXRConfig

class CIHMLCTrainer:
    """
    Trainer engine managing model optimization, evaluation metrics, and 
    experiment telemetry tracking via Weights & Biases.
    """
    def __init__(
        self, 
        model: nn.Module, 
        train_loader: DataLoader, 
        val_loader: DataLoader, 
        test_loader: DataLoader, 
        criterion: nn.Module, 
        optimizer: Optimizer, 
        scheduler: Any, 
        config: CXRConfig
    ) -> None:
        """
        Initializes the trainer engine with the required PyTorch components and data splits.

        Args:
            model (nn.Module): The PyTorch neural network to be trained.
            train_loader (DataLoader): Iterable over the training subset.
            val_loader (DataLoader): Iterable over the validation subset.
            test_loader (DataLoader): Iterable over the held-out test subset.
            criterion (nn.Module): The hierarchical loss function (HBCELoss).
            optimizer (Optimizer): The optimization algorithm.
            scheduler (Any): Learning rate decay scheduler.
            config (CXRConfig): The centralized configuration object.
        """
        self.model = model
        self.train_loader = train_loader
        self.val_loader = val_loader
        self.test_loader = test_loader
        self.criterion = criterion
        self.optimizer = optimizer
        self.scheduler = scheduler
        self.cfg = config
        
        self.best_auc = 0.0
        self.global_step = 0
        self.scaler = torch.amp.GradScaler('cuda')
        
        # Batched GPU Augmentations (Hardware Accelerated)
        self.gpu_train_aug = v2.Compose([
            v2.RandomHorizontalFlip(p=0.5),
            v2.RandomRotation(degrees=10),
            v2.ColorJitter(brightness=0.2, contrast=0.2),
            v2.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
        ])
        
        # Validation Normalization matching Inference parameters
        self.gpu_val_aug = v2.Compose([
            v2.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
        ])

    def _calculate_metrics(self, targets: np.ndarray, probs: np.ndarray, preds: np.ndarray) -> tuple[float, float, float, float]:
        """
        Internal helper to calculate macro-averaged classification metrics.

        Args:
            targets (np.ndarray): Ground truth binary labels.
            probs (np.ndarray): Continuous probability predictions [0, 1].
            preds (np.ndarray): Thresholded binary predictions {0, 1}.

        Returns:
            tuple[float, float, float, float]: Mean AUC, F1 Score, Precision, and Recall.
        """
        try: 
            mean_auc = float(roc_auc_score(targets, probs, average='macro'))
            f1 = float(f1_score(targets, preds, average='macro', zero_division=0))
            precision = float(precision_score(targets, preds, average='macro', zero_division=0))
            recall = float(recall_score(targets, preds, average='macro', zero_division=0))
        except ValueError:
            mean_auc, f1, precision, recall = 0.0, 0.0, 0.0, 0.0
        
        return mean_auc, f1, precision, recall
    
    def train_epoch(self) -> tuple[float, float, float, float ,float]:
        """
        Executes one complete forward and backward pass over the training dataset.

        Returns:
            tuple[float, float, float, float, float]: Epoch Loss, AUC, F1, Precision, Recall.
        """
        self.model.train()
        running_loss = 0.0
        step_running_loss = 0.0
        all_targets, all_probs, all_preds = [], [], []

        total_steps = len(self.train_loader)
        log_step_interval = 50
        console_step_interval = 400 
        
        loop = tqdm(self.train_loader, desc='Training', leave=False)
        for i, (images, labels) in enumerate(loop):
            # Non-blocking transfer to GPU
            images = images.to(self.cfg.device, non_blocking=True)
            labels = labels.to(self.cfg.device, non_blocking=True)
            
            # Apply hardware-accelerated augmentations
            images = self.gpu_train_aug(images)
            
            self.optimizer.zero_grad()
        
            # Automatic Mixed Precision Context Manager
            with torch.amp.autocast('cuda'):
                logits, _ = self.model(images)
                loss = self.criterion(logits, labels)

            # Scale gradients, backward pass, and optimizer step using AMP
            self.scaler.scale(loss).backward()
            self.scaler.step(self.optimizer)
            self.scaler.update()
            
            current_loss = loss.item()
            running_loss += current_loss
            step_running_loss += current_loss

            # Granular Step Logging to WandB
            if (i + 1) % log_step_interval == 0:
                avg_step_loss = step_running_loss / log_step_interval
                wandb.log({
                    "train/step_loss": avg_step_loss,
                    "global_step": self.global_step
                })
                
                # Clean console print based on the larger interval
                if (i + 1) % console_step_interval == 0:
                    tqdm.write(f"  -> Step [{i+1}/{total_steps}] | Moving Avg Loss: {avg_step_loss:.4f}")
                    
                step_running_loss = 0.0

            self.global_step += 1

            # Store predictions for Epoch-level metric calculation
            with torch.no_grad():
                probs = torch.sigmoid(logits)
                preds = (probs > 0.5).float()
                
                all_targets.append(labels.cpu().numpy())
                all_probs.append(probs.cpu().numpy())
                all_preds.append(preds.cpu().numpy())
                
            loop.set_postfix(loss=current_loss)
            
        # Compile epoch-level arrays
        all_targets = np.vstack(all_targets)
        all_probs = np.vstack(all_probs)
        all_preds = np.vstack(all_preds)
            
        epoch_loss = running_loss / total_steps
        auc, f1, precision, recall = self._calculate_metrics(all_targets, all_probs, all_preds)

        return epoch_loss, auc, f1, precision, recall
        
    def evaluate(self, dataloader: DataLoader, desc: str = 'Validating') -> tuple[float, float, float, float, float]:
        """
        Evaluates generalized model performance on a specified subset.

        Args:
            dataloader (DataLoader): The validation or test dataloader.
            desc (str): Description string for the progress bar. Defaults to 'Validating'.

        Returns:
            tuple[float, float, float, float, float]: Epoch Loss, AUC, F1, Precision, Recall.
        """
        self.model.eval()
        total_loss = 0.0
        all_targets, all_probs, all_preds = [], [], []
        
        with torch.no_grad():
            for images, labels in tqdm(dataloader, desc=desc, leave=False):
                images = images.to(self.cfg.device, non_blocking=True)
                labels = labels.to(self.cfg.device, non_blocking=True)

                images = self.gpu_val_aug(images)
                
                logits, _ = self.model(images)
                loss = self.criterion(logits, labels)
                total_loss += loss.item()
                
                probs = torch.sigmoid(logits)
                preds = (probs > 0.5).float()
                
                all_targets.append(labels.cpu().numpy())
                all_probs.append(probs.cpu().numpy())
                all_preds.append(preds.cpu().numpy())
                
        all_targets = np.vstack(all_targets)
        all_probs = np.vstack(all_probs)
        all_preds = np.vstack(all_preds)
            
        epoch_loss = total_loss / len(dataloader)
        auc, f1, precision, recall = self._calculate_metrics(all_targets, all_probs, all_preds)
        
        return epoch_loss, auc, f1, precision, recall
    
    def execute_training(self, save_path: str='densenet_cihmlc.pth') -> None:
        """
        Orchestrates the training loop, early stopping, and WandB telemetry logging.

        Args:
            save_path (str): The local disk path to save the best model weights.
        """
        patience_counter = 0
        
        for epoch in range(self.cfg.epochs):
            print(f"\n========== Epoch {epoch+1}/{self.cfg.epochs} ===========")
            
            t_loss, t_auc, t_f1, t_precision, t_recall = self.train_epoch()
            v_loss, v_auc, v_f1, v_precision, v_recall = self.evaluate(self.val_loader, desc='Validating')

            self.scheduler.step(v_loss)
            current_lr = self.optimizer.param_groups[0]['lr']

            # Epoch-Level WandB Logging
            wandb.log({
                "epoch": epoch + 1,
                "learning_rate": current_lr,
                "train/loss": t_loss, "train/auc": t_auc, "train/f1": t_f1, "train/precision": t_precision, "train/recall": t_recall,
                "val/loss": v_loss, "val/auc": v_auc, "val/f1": v_f1, "val/precision": v_precision, "val/recall": v_recall,
            })
            
            print(f"TRAIN -> Loss: {t_loss:.4f} | AUC: {t_auc:.4f} | F1: {t_f1:.4f} | Precision: {t_precision:.4f} | Recall: {t_recall:.4f}")
            print(f"VALID -> Loss: {v_loss:.4f} | AUC: {v_auc:.4f} | F1: {v_f1:.4f} | Precision: {v_precision:.4f} | Recall: {v_recall:.4f}")
            
            if v_auc > self.best_auc:
                self.best_auc = v_auc
                torch.save(self.model.state_dict(), save_path)
                print(f"*** New Best Model Saved (Val AUC: {v_auc:.4f}) ***")
                patience_counter = 0
            else:
                patience_counter += 1
                
            if patience_counter >= self.cfg.patience:
                print(f"Early stopping triggered after {self.cfg.patience} epochs without improvement.")
                break
            
        print("\n========== Commencing Final Test Set Evaluation ===========")
        self.model.load_state_dict(torch.load(save_path))
        test_loss, test_auc, test_f1, test_precision, test_recall = self.evaluate(self.test_loader, desc='Testing')
        
        wandb.log({
            "test/loss": test_loss, "test/auc": test_auc, "test/f1": test_f1,
            "test/precision": test_precision, "test/recall": test_recall 
        })
        
        print(f"TEST -> Loss: {test_loss:.4f} | AUC: {test_auc:.4f} | F1: {test_f1:.4f} | Precision: {test_precision:.4f} | Recall: {test_recall:.4f}")