import cv2
import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt
from sklearn.metrics import confusion_matrix
from typing import List, Dict

def plot_confusion_matrix(targets: List[int], preds: List[int], class_mapping: Dict[int, str], save_path: str = 'confusion_matrix.png'):
    """Generates and saves a styled Confusion Matrix."""
    cm = confusion_matrix(targets, preds)
    plt.figure(figsize=(10, 8))
    sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', 
                xticklabels=list(class_mapping.values()), 
                yticklabels=list(class_mapping.values()))
    
    plt.title('Validation Confusion Matrix', fontsize=16)
    plt.ylabel('Actual Lesion (Ground Truth)', fontsize=12)
    plt.xlabel('Predicted Lesion (AI)', fontsize=12)
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()
    plt.savefig(save_path)
    print(f"Confusion matrix safely saved to {save_path}")
    plt.close()

def plot_gradcam_overlay(original_tensor, heatmap: np.ndarray, class_name: str, save_path: str = 'gradcam_proof.png'):
    """Generates and saves a side-by-side original and Grad-CAM heatmap comparison."""
    # Un-normalize the image for human viewing
    img_display = original_tensor.permute(1, 2, 0).numpy()
    img_display = (img_display * [0.229, 0.224, 0.225] + [0.485, 0.456, 0.406])
    img_display = np.clip(img_display, 0, 1)

    # Apply the thermal color map to the Grad-CAM math
    heatmap_resized = cv2.resize(heatmap, (224, 224))
    heatmap_colored = cv2.applyColorMap(np.uint8(255 * heatmap_resized), cv2.COLORMAP_JET)
    heatmap_colored = np.float32(heatmap_colored) / 255
    heatmap_colored = heatmap_colored[:, :, ::-1] # Convert BGR to RGB
    overlay = heatmap_colored * 0.5 + img_display * 0.5

    # Plot Side-by-Side
    fig, axes = plt.subplots(1, 2, figsize=(12, 6))
    axes[0].imshow(img_display)
    axes[0].set_title(f"Original Input\nGround Truth: {class_name}")
    axes[0].axis('off')
    
    axes[1].imshow(overlay)
    axes[1].set_title("Grad-CAM AI Focus Area\n(Red = High Importance)")
    axes[1].axis('off')

    plt.tight_layout()
    plt.savefig(save_path)
    print(f"Grad-CAM heatmap safely saved to {save_path}")
    plt.close()