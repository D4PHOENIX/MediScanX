import torch
import numpy as np
import wandb
from tqdm import tqdm
from sklearn.metrics import roc_auc_score, f1_score, precision_score, recall_score

class CIHMLCTrainer:
    """
    Trainer managing model orchestration, metric evaluation, and experiment
    tracking via Weights and Biases.
    
    Attributes:
        model (torch.nn.Module): The PyTorch neural network to be trained.
        train_loader (DataLoader): Iterable over the training dataset.
        val_loader (DataLoader): Iterable over the validation dataset.
        criterion (torch.nn.Module): The loss function (e.g. HBCELoss).
        optimizer (torch.optim.Optimizer): The optimizatoin algorithm.
        scheduler (torch.optim.lr_scheduler): Learning rate decay scheduler.
        cfg (CXRConfig): The centralized configuration object.
        best_auc (float): Tracks the highest achieved validation AUC. 
    """
    def __init__(self, model, train_loader, val_loader, test_loader, criterion, optimizer, scheduler, config):
        """Initializes the CIHMLCTrainer with the require PyTorch components and configs."""
        self.model = model
        self.train_loader = train_loader
        self.val_loader = val_loader
        self.test_loader = test_loader
        self.criterion = criterion
        self.optimizer = optimizer
        self.scheduler = scheduler
        self.cfg = config
        self.best_auc = 0.0

    def _calculate_metrics(self, targets: np.ndarray, probs: np.ndarray, preds: np.ndarray) -> tuple:
        """Internal helper to calculate macro-averaged classification metrics."""
        try: 
            mean_auc = float(roc_auc_score(all_targets, all_probs, average='macro'))
            f1 = float(f1_score(all_targets, all_probs, average='macro', zero_division=0))
            precison = float(precision_score(all_targets, all_probs, average='macro', zero_division=0))
            recall = float(recall_score(all_targets, all_probs, average='macro', zero_division=0))
        except ValueError:
            # Fallback if a batch lacks positive samples for minority classes
            mean_auc, f1, precision, recall = 0.0, 0.0, 0.0, 0.0
        
        return mean_auc, f1, precision, recall
    
    def train_epoch(self) -> float:
        """
        Executes one complete pass over the training dataset.

        Returns:
            tuple: Contains (train_loss, train_auc, train_f1, train_precision, train_recall)
        """
        self.model.train()
        running_loss = 0.0
        all_targets, all_probs, all_preds = [], [], []
        
        loop = tqdm(self.train_loader, desc='Training', leave=False)
        for images, labels in loop:
            images, labels = images.to(self.cfg.device), labels.to(self.cfg.device)
            
            self.optimizer.zero_grad()
            logits, _ = self.model(images)
            loss = self.criterion(logits, labels)
            
            loss.backward()
            self.optimizer.step()
            running_loss += loss.item()
            loop.set_postfix(loss=loss.item())
        
        # Store predictions for epoch-level metric calculation
        with torch.no_grad():
            probs = torch.sigmoid(logits)
            preds = (probs > 0.5).float()
            all_targets.append(labels.cpu().numpy())
            all_probs.append(probs.cpu().numpy())
            all_preds.append(preds.cpu().numpy())
            
        epoch_loss = running_loss / len(self.train_loader)
        auc, f1, precision, recall = self._calculate_metrics(all_targets, all_probs, all_preds)

        return epoch_loss, auc, f1, precision, recall
        
    def evaluate(self, dataloader: DataLoader, desc: str ='validating') -> tuple:
        """
        Evaluates the model on the provided dataloader.

        Args:
            dataloader (DataLoader): The validation or the test dataset loader.
            desc (str, optional): The description for the tqdm progress bar. Defaults to 'validating'.

        Returns:
            tuple: Contains (loss, macro_auc, macro_f1, macro_precision, macro_recall).
        """
        self.model.eval()
        total_loss = 0.0
        all_targets, all_probs, all_preds = [], [], []
        
        with torch.no_grad():
            for images, labels in tqdm(dataloader, desc=desc, leave=False):
                images, labels = images.to(self.cfg.device), labels.to(self.cfg.device)
                
                logits, _ = self.model(images)
                loss = self.criterion(logits, labels)
                total_loss += loss.item()
                
                # Convert raw logits to probabilites and binary predictions (0.5 threshold)
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
    
    def execute_training(self, save_path: str='best_densenet_cihmlc.pth') -> None:
        """
        Orchestrates the training loop, early stopping and WandB telemetry logging.
        Automatically executes final test-set evaluation upon completion.

        Args:
            save_path (str, optional): Filepath to save the best model weights. Defaults to 'best_densenet_cihmlc.pth'.
        """
        patience_counter = 0
        
        for epoch in range(self.cfg.epochs):
            print(f"\n========== Epoch {epoch+1}/{self.cfg.epochs} ===========")
            
            # Train and evaluate
            t_loss, t_auc, t_f1, t_precision, t_recall = self.train_epoch()
            v_loss, v_auc, v_f1, v_precision, v_recall = self.evaluate(self.val_loader, desc='Validating')

            # Step Scheduler
            self.scheduler.step(v_loss)
            current_lr = self.optimizer.param_groups[0]['lr']

            # WandB Logging (per Epoch)
            wandb.log({
                "epoch": epoch + 1,
                "learning_rate": current_lr,
                "train/loss": t_loss, "train/auc": t_auc, "train/f1": t_f1, "train/precision": t_precision, "train/recall": t_recall,
                "val/loss": v_loss, "val/auc": v_auc, "val/f1": v_f1, "val/precision": v_precision, "val/recall": v_recall,
            })
            
            print(f"TRAIN -> Loss: {t_loss:.4f} | AUC: {t_auc:.4f} | F1: {t_f1} | Precision: {t_precision:.4f} | Recall: {t_recall:.4f}")
            print(f"VALID -> Loss: {v_loss:.4f} | AUC: {v_auc:.4f} | F1: {v_f1} | Precision: {v_precision:.4f} | Recall: {v_recall:.4f}")
            
            # Checkpointing and Early Stopping
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
            
        # Final Test Set Evaluation
        print("\n========== Commencing Final Test Set Evaluation ===========")
        self.model.load_state_dict(torch.load(save_path))
        test_loss, test_auc, test_f1, test_precision, test_recall = self.evaluate(self.test_loader, desc='Testing')
        
        wandb.log({
            "test/loss": test_loss, "test/auc": test_auc, "test/f1": test_f1,
            "test/precision": test_precision, "test/recall": test_recall 
            
        })
        
        print(f"TEST -> Loss: {test_loss:.4f} | AUC: {test_auc:.4f} | F1: {test_f1} | Precision: {test_precision:.4f} | Recall: {test_recall:.4f}")
        