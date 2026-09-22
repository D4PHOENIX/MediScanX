"""ECG Dual-Branch Multi-Source classifier — production inference module.

Implements the DualBranchECGClassifier architecture fusing:
  1. Spatial 12-Lead Morphology Branch (12, 250) -> Conv1D x 3 + BiLSTM -> 128-d
  2. Temporal Lead II Rhythm Branch (1, 1000) -> Conv1D x 3 + BiLSTM -> 64-d
  3. Voltage Amplitude Vector (12,) -> Linear(12->32) + BN + ReLU -> 32-d
  4. Fusion Head: Concat(224) -> Linear(128) -> Dropout -> Logits(5)

Exposes backward-compatible interfaces:
  - ECGClassifier alias pointing to DualBranchECGClassifier
  - conv3 property hooking morph_conv3 for 1D Grad-CAM
  - forward() with auto-synthesised rhythm and voltage fallbacks if called with a single tensor
"""

import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F

logger: logging.Logger = logging.getLogger(__name__)


class DualBranchECGClassifier(nn.Module):
    """Production Dual-Branch Spatial-Temporal ECG pathology classifier.

    Args:
        num_leads (int): Number of ECG input channels (default 12).
        num_classes (int): Number of output logit dimensions (default 5).

    Attributes:
        morph_conv1, morph_conv2, morph_conv3 (nn.Conv1d): Spatial morphology trunk.
        morph_bn1, morph_bn2, morph_bn3 (nn.BatchNorm1d): Morphology batch normalisation.
        morph_pool (nn.MaxPool1d): Max pooling for morphology stages.
        morph_lstm (nn.LSTM): Bidirectional LSTM for morphology temporal encoding.
        morph_fc (nn.Linear): 128-d projection for morphology branch.
        rhythm_conv1, rhythm_conv2, rhythm_conv3 (nn.Conv1d): Lead II rhythm strip trunk.
        rhythm_bn1, rhythm_bn2, rhythm_bn3 (nn.BatchNorm1d): Rhythm batch normalisation.
        rhythm_pool (nn.MaxPool1d): Max pooling for rhythm stages.
        rhythm_lstm (nn.LSTM): Bidirectional LSTM for continuous rhythm encoding.
        rhythm_fc (nn.Linear): 64-d projection for rhythm branch.
        voltage_fc (nn.Sequential): Voltage amplitude MLP preserving physical mV criteria.
        fusion_fc1 (nn.Linear): Fusion projection layer (224 -> 128).
        fusion_dropout (nn.Dropout): Regularisation dropout.
        fusion_fc2 (nn.Linear): Final linear classifier outputting raw logits.
    """

    def __init__(self, num_leads: int = 12, num_classes: int = 5) -> None:
        """Initialise DualBranchECGClassifier layers.

        Args:
            num_leads (int): Number of ECG input channels (default 12).
            num_classes (int): Number of output logit dimensions (default 5).
        """
        super().__init__()
        self.num_leads: int = num_leads
        self.num_classes: int = num_classes

        # ── BRANCH 1: Spatial 12-Lead Morphology Backbone (12, 250) ───────
        self.morph_conv1: nn.Conv1d = nn.Conv1d(num_leads, 64, kernel_size=7, padding=3, bias=False)
        self.morph_bn1: nn.BatchNorm1d = nn.BatchNorm1d(64)
        self.morph_conv2: nn.Conv1d = nn.Conv1d(64, 128, kernel_size=5, padding=2, bias=False)
        self.morph_bn2: nn.BatchNorm1d = nn.BatchNorm1d(128)
        self.morph_conv3: nn.Conv1d = nn.Conv1d(128, 256, kernel_size=3, padding=1, bias=False)
        self.morph_bn3: nn.BatchNorm1d = nn.BatchNorm1d(256)
        self.morph_pool: nn.MaxPool1d = nn.MaxPool1d(kernel_size=2)
        self.morph_lstm: nn.LSTM = nn.LSTM(
            input_size=256,
            hidden_size=128,
            num_layers=2,
            batch_first=True,
            bidirectional=True,
            dropout=0.3,
        )
        self.morph_fc: nn.Linear = nn.Linear(256, 128)

        # ── BRANCH 2: Temporal Lead II Rhythm Encoder (1, 1000) ───────────
        self.rhythm_conv1: nn.Conv1d = nn.Conv1d(1, 32, kernel_size=15, stride=2, padding=7, bias=False)
        self.rhythm_bn1: nn.BatchNorm1d = nn.BatchNorm1d(32)
        self.rhythm_conv2: nn.Conv1d = nn.Conv1d(32, 64, kernel_size=7, stride=2, padding=3, bias=False)
        self.rhythm_bn2: nn.BatchNorm1d = nn.BatchNorm1d(64)
        self.rhythm_conv3: nn.Conv1d = nn.Conv1d(64, 128, kernel_size=5, stride=1, padding=2, bias=False)
        self.rhythm_bn3: nn.BatchNorm1d = nn.BatchNorm1d(128)
        self.rhythm_pool: nn.MaxPool1d = nn.MaxPool1d(kernel_size=2)
        self.rhythm_lstm: nn.LSTM = nn.LSTM(
            input_size=128,
            hidden_size=64,
            num_layers=2,
            batch_first=True,
            bidirectional=True,
            dropout=0.3,
        )
        self.rhythm_fc: nn.Linear = nn.Linear(128, 64)

        # ── BRANCH 3: Voltage Amplitude Feature MLP (12,) ─────────────────
        self.voltage_fc: nn.Sequential = nn.Sequential(
            nn.Linear(num_leads, 32),
            nn.BatchNorm1d(32),
            nn.ReLU(),
        )

        # ── FUSION HEAD (128 + 64 + 32 = 224) ─────────────────────────────
        self.fusion_fc1: nn.Linear = nn.Linear(128 + 64 + 32, 128)
        self.fusion_dropout: nn.Dropout = nn.Dropout(p=0.4)
        self.fusion_fc2: nn.Linear = nn.Linear(128, num_classes)

    @property
    def conv3(self) -> nn.Conv1d:
        """Alias returning morph_conv3 as the target layer for 1D Grad-CAM hooks."""
        return self.morph_conv3

    def extract_features(self, x: torch.Tensor) -> torch.Tensor:
        """Run the spatial CNN trunk and return morphology feature maps.

        This is the hook point for Grad-CAM on ``self.morph_conv3``.

        Args:
            x (torch.Tensor): Normalised 12-lead signals of shape ``(B, 12, 250)``.

        Returns:
            torch.Tensor: Feature maps of shape ``(B, 256, 31)``.
        """
        x = self.morph_pool(F.relu(self.morph_bn1(self.morph_conv1(x))))
        x = self.morph_pool(F.relu(self.morph_bn2(self.morph_conv2(x))))
        x = self.morph_pool(F.relu(self.morph_bn3(self.morph_conv3(x))))
        return x

    def forward(
        self,
        x_morph: torch.Tensor,
        x_rhythm: Optional[torch.Tensor] = None,
        x_volt: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """Dual-Branch forward pass.

        Supports two invocation signatures:
          1. Full multi-source: ``forward(x_morph, x_rhythm, x_volt)``
          2. Single-tensor fallback: ``forward(x_morph)`` (interpolates rhythm from
             Lead II and derives peak-to-peak voltages for backward compatibility).

        Args:
            x_morph (torch.Tensor): Morphology segment of shape ``(B, 12, 250)``.
            x_rhythm (Optional[torch.Tensor]): Lead II continuous rhythm of shape ``(B, 1, 1000)``.
            x_volt (Optional[torch.Tensor]): Peak-to-peak voltage amplitudes of shape ``(B, 12)``.

        Returns:
            torch.Tensor: Raw logits of shape ``(B, 5)``.
        """
        # 1. Branch 1: Spatial 12-Lead Morphology
        m = self.extract_features(x_morph)
        m_seq, _ = self.morph_lstm(m.permute(0, 2, 1))
        m_feat = F.relu(self.morph_fc(torch.mean(m_seq, dim=1)))

        # 2. Branch 2: Temporal Continuous Lead II Rhythm Strip
        if x_rhythm is None:
            # Fallback: extract Lead II (index 1) and interpolate to 1000 samples
            lead_idx = 1 if x_morph.shape[1] > 1 else 0
            lead2 = x_morph[:, lead_idx: lead_idx + 1, :]
            x_rhythm = F.interpolate(lead2, size=1000, mode="linear", align_corners=False)

        r = self.rhythm_pool(F.relu(self.rhythm_bn1(self.rhythm_conv1(x_rhythm))))
        r = self.rhythm_pool(F.relu(self.rhythm_bn2(self.rhythm_conv2(r))))
        r = F.relu(self.rhythm_bn3(self.rhythm_conv3(r)))
        r_seq, _ = self.rhythm_lstm(r.permute(0, 2, 1))
        r_feat = F.relu(self.rhythm_fc(torch.mean(r_seq, dim=1)))

        # 3. Branch 3: Physical Voltage Amplitude Preservation
        if x_volt is None:
            # Fallback: compute peak-to-peak amplitude from morphology tensor
            x_volt = torch.amax(x_morph, dim=-1) - torch.amin(x_morph, dim=-1)

        v_feat = self.voltage_fc(x_volt)

        # 4. Multimodal Feature Fusion Head
        fused = torch.cat([m_feat, r_feat, v_feat], dim=1)
        hidden = self.fusion_dropout(F.relu(self.fusion_fc1(fused)))
        return self.fusion_fc2(hidden)

    # -------------------------------------------------------------------------
    #  Factory / checkpoint loader
    # -------------------------------------------------------------------------

    @classmethod
    def from_checkpoint(
        cls,
        ckpt_path: str,
        device: Optional[torch.device] = None,
        num_leads: int = 12,
        num_classes: int = 5,
    ) -> "DualBranchECGClassifier":
        """Load a PyTorch Lightning checkpoint into a bare ``DualBranchECGClassifier``.

        Lightning prepends a ``'model.'`` prefix to all backbone parameter keys
        when it wraps an ``nn.Module`` in a ``LightningModule``. Metric and
        criterion keys (``accuracy.*``, ``criterion.*``, etc.) that have no
        counterpart in the bare module are silently discarded.

        Args:
            ckpt_path (str): Path to the ``.ckpt`` file.
            device (Optional[torch.device]): Target device; defaults to CPU if ``None``.
            num_leads (int): Number of input channels to initialise the model with.
            num_classes (int): Number of output logits.

        Returns:
            DualBranchECGClassifier: Model instance in ``eval()`` mode with weights loaded.

        Raises:
            FileNotFoundError: If ``ckpt_path`` does not exist on disk.
        """
        if device is None:
            device = torch.device("cpu")

        path: Path = Path(ckpt_path)
        if not path.exists():
            raise FileNotFoundError(
                f"ECG checkpoint not found at '{path}'. "
                "Ensure the weights volume is mounted at /models."
            )

        import sys

        for stub_name in ["MultiSourceTrainingConfig", "RhythmTrainingConfig", "TrainingConfig"]:
            main_mod = sys.modules.get("__main__")
            if main_mod and not hasattr(main_mod, stub_name):
                stub_cls = type(stub_name, (), {})
                setattr(main_mod, stub_name, stub_cls)
                if hasattr(torch.serialization, "add_safe_globals"):
                    try:
                        torch.serialization.add_safe_globals([stub_cls])
                    except Exception:
                        pass

        try:
            ckpt: Dict[str, Any] = torch.load(
                str(path),
                map_location="cpu",
                weights_only=False,
            )
        except Exception as exc:
            logger.warning(
                "Standard unpickling failed (%s); trying fallback load.", exc
            )
            ckpt = torch.load(str(path), map_location="cpu")

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

        model: DualBranchECGClassifier = cls(num_leads=num_leads, num_classes=num_classes)
        missing: Any
        unexpected: Any
        missing, unexpected = model.load_state_dict(clean, strict=False)

        if missing:
            logger.warning(
                "DualBranchECGClassifier.from_checkpoint: %d missing key(s): %s",
                len(missing),
                missing,
            )
        if unexpected:
            logger.warning(
                "DualBranchECGClassifier.from_checkpoint: %d unexpected key(s): %s",
                len(unexpected),
                unexpected,
            )

        model.to(device)
        model.eval()
        logger.info(
            "DualBranchECGClassifier loaded from checkpoint '%s' on %s.", path.name, device
        )
        return model


# Backward-compatible alias for existing callers and test suites
ECGClassifier = DualBranchECGClassifier

