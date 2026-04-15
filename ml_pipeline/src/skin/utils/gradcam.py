import torch
import numpy as np

class MobileNetGradCAM:
    """Lightweight Grad-CAM implementation for MobileNet architectures."""
    
    def __init__(self, model):
        self.model = model
        self.gradients = None
        self.activations = None
        
        # Hook into the very last convolutional block before the pooling/classifier
        target_layer = self.model.model.features[-1]
        target_layer.register_forward_hook(self.save_activation)
        target_layer.register_full_backward_hook(self.save_gradient)

    def save_activation(self, module, input, output):
        self.activations = output

    def save_gradient(self, module, grad_input, grad_output):
        self.gradients = grad_output[0]

    def __call__(self, x: torch.Tensor, class_idx: int) -> np.ndarray:
        # Ensure gradients are enabled for Grad-CAM math
        with torch.enable_grad():
            logits = self.model(x)
            self.model.zero_grad()
            
            # Target the specific class prediction
            loss = logits[0, class_idx]
            loss.backward()
            
            # Weight the activations by the gradients
            pooled_gradients = torch.mean(self.gradients, dim=[0, 2, 3])
            self.activations = self.activations * pooled_gradients.view(1, -1, 1, 1)
                
            heatmap = torch.mean(self.activations, dim=1).squeeze().cpu().detach().numpy()
            heatmap = np.maximum(heatmap, 0) # Apply ReLU
            heatmap /= np.max(heatmap) + 1e-8 # Normalize between 0 and 1
            
            return heatmap