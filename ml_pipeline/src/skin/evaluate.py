import torch
from torch.serialization import add_safe_globals
import glob
import os

# Import our custom modules
from src.skin.config import SkinConfig
from src.skin.data.datamodule import SkinDataModule
from src.skin.models.mobilenet import MediScanX_Skin_Baseline
from src.skin.utils.gradcam import MobileNetGradCAM
from src.skin.utils.visualizations import plot_confusion_matrix, plot_gradcam_overlay

def main():
    # 1. Configuration & Security Fix
    config = SkinConfig()
    add_safe_globals([SkinConfig]) # Allow PyTorch to load our custom config class safely
    
    # Dynamically find the best checkpoint in the models directory
    checkpoints = glob.glob("models/*.ckpt")
    if not checkpoints:
        raise FileNotFoundError("No checkpoint files found in the 'models/' directory. Please run training first.")
    
    # Auto-select the most recently modified checkpoint
    checkpoint_path = max(checkpoints, key=os.path.getmtime) 

    # 2. Setup Data Pipeline
    print("Initializing Data Pipeline...")
    data_module = SkinDataModule(config)
    data_module.prepare_data()
    data_module.setup(stage='fit')
    
    # 3. Load Model
    print(f"Loading optimal weights from: {checkpoint_path}")
    model = MediScanX_Skin_Baseline.load_from_checkpoint(
        checkpoint_path, 
        config=config, 
        class_weights=data_module.class_weights
    )
    model.eval()
    model.to("cuda" if torch.cuda.is_available() else "cpu")

    # 4. Generate Confusion Matrix
    print("Evaluating validation set...")
    all_preds, all_targets = [], []
    val_loader = data_module.val_dataloader()

    with torch.no_grad():
        for x, y in val_loader:
            x = x.to(model.device)
            logits = model(x)
            preds = torch.argmax(logits, dim=1).cpu().numpy()
            all_preds.extend(preds)
            all_targets.extend(y.numpy())

    # CLEANED UP: Call the function from visualizations.py
    plot_confusion_matrix(all_targets, all_preds, data_module.idx_to_class)

    # 5. Generate Grad-CAM Heatmap
    print("Generating Grad-CAM XAI Proof...")
    sample_imgs, sample_labels = next(iter(val_loader))
    sample_img, sample_label = sample_imgs[0], sample_labels[0]
    sample_tensor = sample_img.unsqueeze(0).to(model.device).requires_grad_(True)

    cam_generator = MobileNetGradCAM(model)
    heatmap = cam_generator(sample_tensor, sample_label.item())

    # CLEANED UP: Call the function from visualizations.py
    plot_gradcam_overlay(sample_img, heatmap, data_module.idx_to_class[sample_label.item()])

if __name__ == "__main__":
    main()