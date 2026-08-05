"""ECG V2 CNN-BiLSTM classifier — bare ``nn.Module`` for production inference.

This is the ``NakedECGBackbone`` from V2 Notebook 05, renamed ``ECGClassifier``
and extended with a ``from_checkpoint`` factory that strips the Lightning
``'model.'`` prefix from checkpoint state_dict keys.

Design constraints
------------------
- No PyTorch Lightning imports, hooks, metrics, or optimisers.
- ``extract_features()`` is exposed as a public method so ``GradCAM1D`` can
  register a forward hook on ``self.conv3`` without walking the module tree.
- ``forward()`` delegates to ``extract_features`` → ``classify_features`` to
  keep the call graph clean for backward-pass computation.

Architecture (V2, 12-Lead Paper Digitisation)
---------------------------------------------
Input:  (B, 12, 500)  — batch × leads × timesteps
After conv1 + pool1:  (B, 64,  250)
After conv2 + pool2:  (B, 128, 125)
After conv3 + pool3:  (B, 256,  62)  ← Grad-CAM hook target
After BiLSTM:         (B,  62, 256)  — 128 hidden × 2 directions
After mean pool:      (B, 256)
After fc1 + dropout:  (B, 128)
Output logits:        (B,   5)  — NORM, MI, STTC, CD, HYP (raw, pre-sigmoid)
"""

import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F

logger: logging.Logger = logging.getLogger(__name__)


class ECGClassifier(nn.Module):
    """Production-only 1D CNN-BiLSTM ECG pathology classifier.

    Args:
        num_leads (int): Number of ECG input channels (default 12).
        num_classes (int): Number of output logit dimensions (default 5).

    Attributes:
        conv1 (nn.Conv1d): First convolutional layer extracting initial spatial features.
        bn1 (nn.BatchNorm1d): Batch normalisation for the first convolutional layer.
        pool1 (nn.MaxPool1d): Max pooling for the first convolutional layer.
        conv2 (nn.Conv1d): Second convolutional layer extracting deeper spatial features.
        bn2 (nn.BatchNorm1d): Batch normalisation for the second convolutional layer.
        pool2 (nn.MaxPool1d): Max pooling for the second convolutional layer.
        conv3 (nn.Conv1d): Third convolutional layer; acts as Grad-CAM hook target.
        bn3 (nn.BatchNorm1d): Batch normalisation for the third convolutional layer.
        pool3 (nn.MaxPool1d): Max pooling for the third convolutional layer.
        lstm (nn.LSTM): Bidirectional LSTM for temporal context encoding.
        fc1 (nn.Linear): First fully-connected layer for classification.
        dropout (nn.Dropout): Dropout layer for regularisation.
        fc2 (nn.Linear): Final fully-connected layer outputting raw class logits.
    """

    def __init__(self, num_leads: int = 12, num_classes: int = 5) -> None:
        """Initialise the ECGClassifier with specific layers.

        Args:
            num_leads (int): Number of ECG input channels (default 12).
            num_classes (int): Number of output logit dimensions (default 5).
        """
        super().__init__()

        # Convolutional feature extractor (3rd Experimentation architecture)
        # Three progressively deeper stages, shared pool halving temporal axis.
        self.conv1: nn.Conv1d = nn.Conv1d(num_leads, 64, kernel_size=7, padding=3, bias=False)
        self.bn1: nn.BatchNorm1d = nn.BatchNorm1d(64)

        self.conv2: nn.Conv1d = nn.Conv1d(64, 128, kernel_size=5, padding=2, bias=False)
        self.bn2: nn.BatchNorm1d = nn.BatchNorm1d(128)

        # conv3 is the Grad-CAM target layer — its output is hooked by GradCAM1D.
        self.conv3: nn.Conv1d = nn.Conv1d(128, 256, kernel_size=3, padding=1, bias=False)
        self.bn3: nn.BatchNorm1d = nn.BatchNorm1d(256)

        # Single shared max-pooling layer (used after each conv stage)
        self.pool: nn.MaxPool1d = nn.MaxPool1d(kernel_size=2)

        # Temporal context encoder 
        # Bidirectional: hidden_size 128 × 2 directions = 256 output features.
        self.lstm: nn.LSTM = nn.LSTM(
            input_size=256,
            hidden_size=128,
            num_layers=2,
            batch_first=True,
            bidirectional=True,
            dropout=0.3,
        )

        # Classification 
        self.fc1: nn.Linear = nn.Linear(256, 128)
        self.dropout: nn.Dropout = nn.Dropout(p=0.4)
        self.fc2: nn.Linear = nn.Linear(128, num_classes)

    # -------------------------------------------------------------------------
    #  Public inference interface
    # -------------------------------------------------------------------------

    def extract_features(self, x: torch.Tensor) -> torch.Tensor:
        """Run the CNN trunk and return spatial feature maps.

        This is the natural split point for Grad-CAM: a forward hook registered
        on ``self.conv3`` will capture the post-activation output produced here.

        Args:
            x (torch.Tensor): Normalised 12-lead signals of shape ``(B, 12, 250)``.

        Returns:
            torch.Tensor: Convolutional feature maps of shape ``(B, 256, 31)``.
        """
        x = self.pool(F.relu(self.bn1(self.conv1(x))))  # (B, 64,  125)
        x = self.pool(F.relu(self.bn2(self.conv2(x))))  # (B, 128,  62)
        x = self.pool(F.relu(self.bn3(self.conv3(x))))  # (B, 256,  31)
        return x

    def classify_features(self, features: torch.Tensor) -> torch.Tensor:
        """Classify pre-extracted CNN feature maps via BiLSTM + FC head.

        Args:
            features (torch.Tensor): CNN output of shape ``(B, 256, 31)``.

        Returns:
            torch.Tensor: Raw logits of shape ``(B, 5)``.
        """
        # Permute: (B, 256, 31) → (B, 31, 256) for LSTM batch_first convention
        seq: torch.Tensor
        _: torch.Tensor
        seq, _ = self.lstm(features.permute(0, 2, 1))  # (B, 31, 256)

        # Global average pooling over the temporal dimension
        pooled: torch.Tensor = torch.mean(seq, dim=1)                # (B, 256)

        hidden: torch.Tensor = F.relu(self.fc1(pooled))              # (B, 128)
        hidden = self.dropout(hidden)
        return self.fc2(hidden)                        # (B, 5)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Full forward pass: CNN trunk → BiLSTM head → logits.

        Args:
            x (torch.Tensor): Batch of normalised 12-lead ECG signals. Shape: ``(B, 12, 250)``.

        Returns:
            torch.Tensor: Raw (pre-sigmoid) class logits. Shape: ``(B, 5)``.
                Apply ``torch.sigmoid()`` to obtain per-class probabilities.
        """
        features: torch.Tensor = self.extract_features(x)
        return self.classify_features(features)

    # -------------------------------------------------------------------------
    #  Factory / checkpoint loader
    # -------------------------------------------------------------------------

    @staticmethod
    def from_checkpoint(
        ckpt_path: str,
        device: Optional[torch.device] = None,
        num_leads: int = 12,
        num_classes: int = 5,
    ) -> "ECGClassifier":
        """Load a PyTorch Lightning checkpoint into a bare ``ECGClassifier``.

        Lightning prepends a ``'model.'`` prefix to all backbone parameter keys
        when it wraps an ``nn.Module`` in a ``LightningModule``. Metric and
        criterion keys (``accuracy.*``, ``criterion.*``, etc.) that have no
        counterpart in the bare module are silently discarded.

        Args:
            ckpt_path (str): Path to the ``.ckpt`` file from fine-tuning (Notebook 04).
            device (Optional[torch.device]): Target device; defaults to CPU if ``None``.
            num_leads (int): Number of input channels to initialise the model with.
            num_classes (int): Number of output logits.

        Returns:
            ECGClassifier: Model instance in ``eval()`` mode with weights loaded.

        Raises:
            FileNotFoundError: If ``ckpt_path`` does not exist on disk.
                Callers should convert this to ``ECGModelNotFoundError`` at the
                engine layer to preserve the domain exception hierarchy.
        """
        if device is None:
            device = torch.device("cpu")

        path: Path = Path(ckpt_path)
        if not path.exists():
            raise FileNotFoundError(
                f"ECG checkpoint not found at '{path}'. "
                "Ensure the weights volume is mounted at /models."
            )

        ckpt: Dict[str, Any] = torch.load(
            str(path),
            map_location="cpu",
            weights_only=False,
        )
        state_dict: Dict[str, Any] = ckpt.get("state_dict", ckpt)

        # Strip Lightning's 'model.' prefix; drop metric / criterion keys that
        # have no corresponding parameter in the bare nn.Module.
        _ignore_prefixes: Tuple[str, ...] = (
            "criterion",
            "accuracy",
            "precision",
            "recall",
            "f1_score",
            "train_",
            "val_",
        )
        clean: Dict[str, torch.Tensor] = {
            k.replace("model.", "", 1): v
            for k, v in state_dict.items()
            if not any(k.startswith(p) for p in _ignore_prefixes)
        }

        model: ECGClassifier = ECGClassifier(num_leads=num_leads, num_classes=num_classes)
        missing: Any
        unexpected: Any
        missing, unexpected = model.load_state_dict(clean, strict=False)

        if missing:
            logger.warning(
                "ECGClassifier.from_checkpoint: %d missing key(s): %s",
                len(missing),
                missing,
            )
        if unexpected:
            logger.warning(
                "ECGClassifier.from_checkpoint: %d unexpected key(s): %s",
                len(unexpected),
                unexpected,
            )

        model.to(device)
        model.eval()
        logger.info(
            "ECGClassifier loaded from checkpoint '%s' on %s.", path.name, device
        )
        return model
