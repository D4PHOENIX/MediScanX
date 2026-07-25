"""Dual-input ECG preprocessing pipeline."""

import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

import cv2
import numpy as np
import torch
import wfdb
from scipy.signal import resample

from app.core.config import Settings
from app.core.exceptions import (
    ECGFileReadError,
    SignalProcessingError,
    SignalLengthMismatchError,
    InvalidLeadCountError,
    ECGExtractionError,
)

logger: logging.Logger = logging.getLogger(__name__)


# ── Private optical preprocessing classes ──────────────────────────────────

class _AdaptiveGridRemover:
    """Removes the background grid using adaptive geometry (V2).
    Immune to grayscale, bad lighting, and varying color spaces.

    Attributes:
        cfg (Settings): Preprocessing configuration constraints.
    """
    def __init__(self, cfg: Settings) -> None:
        """Initialise grid remover with specific configuration.

        Args:
            cfg (Settings): The preprocessor configuration.
        """
        self.cfg: Settings = cfg

    def remove_grid(self, image_path: str) -> np.ndarray:
        """Process image to geometrically remove the grid.

        Args:
            image_path (str): File path to the ECG input image.

        Returns:
            np.ndarray: Binary image with the grid removed.

        Raises:
            ECGFileReadError: If the image is not found or fails to read.
        """
        img: np.ndarray = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise ECGFileReadError(f"Image not found at path: {image_path}")

        # 1. Adaptive Thresholding (Handles shadows and dim lighting)
        binary: np.ndarray = cv2.adaptiveThreshold(
            img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 21, 10
        )

        # 2. Morphological Grid Subtraction (Geometry instead of Color)
        horizontal_kernel: np.ndarray = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
        remove_horizontal: np.ndarray = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel, iterations=1)
        
        vertical_kernel: np.ndarray = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40))
        remove_vertical: np.ndarray = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vertical_kernel, iterations=1)
        
        grid: np.ndarray = cv2.add(remove_horizontal, remove_vertical)
        trace_only: np.ndarray = cv2.subtract(binary, grid)

        cleanup_kernel: np.ndarray = np.ones((3, 3), np.uint8)
        clean_trace: np.ndarray = cv2.morphologyEx(trace_only, cv2.MORPH_OPEN, cleanup_kernel, iterations=1)

        return clean_trace


class _ECGGridSlicer:
    """Slices the cleaned binary ECG image into 12 lead rectangles.

    Attributes:
        cfg (Settings): Configuration for grid dimensions.
    """
    def __init__(self, cfg: Settings) -> None:
        """Initialise grid slicer.

        Args:
            cfg (Settings): Preprocessor configuration.
        """
        self.cfg: Settings = cfg

    def slice_image(self, binary_img: np.ndarray) -> Dict[str, np.ndarray]:
        """Slice the binary image into a dictionary mapping lead names to image arrays.

        Args:
            binary_img (np.ndarray): Binary image of the entire ECG.

        Returns:
            Dict[str, np.ndarray]: Mapped snippets for each ECG lead.
        """
        height: int
        width: int
        height, width = binary_img.shape
        usable_height: int = int(height * self.cfg.usable_height_ratio)
        box_width: int = width // self.cfg.grid_cols
        box_height: int = usable_height // self.cfg.grid_rows

        extracted: Dict[str, np.ndarray] = {}
        r: int
        c: int
        for r in range(self.cfg.grid_rows):
            for c in range(self.cfg.grid_cols):
                y_start: int = r * box_height
                y_end: int = (r + 1) * box_height
                x_start: int = c * box_width
                x_end: int = (c + 1) * box_width
                snippet: np.ndarray = binary_img[y_start:y_end, x_start:x_end]
                lead_name: str = self.cfg.lead_layout[r][c]
                extracted[lead_name] = snippet
        return extracted


class _WaveformDigitizer:
    """Converts a binary lead image into a 1‑D normalised signal.

    Attributes:
        cfg (Settings): Pipeline configuration.
    """
    def __init__(self, cfg: Settings) -> None:
        """Initialise waveform digitiser.

        Args:
            cfg (Settings): The preprocessor configuration.
        """
        self.cfg: Settings = cfg

    def extract_1d_signal(self, lead_img: np.ndarray) -> Tuple[Optional[np.ndarray], float, bool]:
        """Extract a 1D signal from a binary slice of a lead safely.

        Args:
            lead_img (np.ndarray): Sliced image for a specific lead.

        Returns:
            Tuple[Optional[np.ndarray], float, bool]: The normalised 1D signal array (or None if failed), fractional coverage, and boolean flag if span fails.
        """
        height: int
        width: int
        height, width = lead_img.shape
        
        raw_signal: np.ndarray = np.zeros(width, dtype=np.float32)
        valid_cols_count: int = 0
        
        for x in range(width):
            column: np.ndarray = lead_img[:, x]
            y_coords: np.ndarray = np.where(column > 0)[0]
            if len(y_coords) > 0:
                raw_signal[x] = np.mean(y_coords)
                valid_cols_count += 1
            else:
                # Safe masking to prevent Inf crash during interpolation
                raw_signal[x] = np.nan

        coverage: float = float(valid_cols_count / width)
        
        if valid_cols_count < 2:
            return None, coverage, True

        valid_mask: np.ndarray = ~np.isnan(raw_signal)
        valid_x_arr: np.ndarray = np.where(valid_mask)[0]
        
        x_min: int = valid_x_arr[0]
        x_max: int = valid_x_arr[-1]
        span_fraction: float = (x_max - x_min + 1) / width
        
        # Genuine span check: reject if the trace spans less than 50% of the box width
        if span_fraction < 0.5:
            return None, coverage, True

        # Safe interpolation over the missing NaN gaps
        raw_signal[~valid_mask] = np.interp(
            np.flatnonzero(~valid_mask),
            np.flatnonzero(valid_mask),
            raw_signal[valid_mask]
        )
        
        # Invert to Cartesian math coordinates
        amplitudes: np.ndarray = height - raw_signal
        
        # Isolate the exact genuine span to avoid padding artifacts
        cropped_signal: np.ndarray = amplitudes[x_min:x_max+1]
        resampled: np.ndarray = resample(cropped_signal, self.cfg.seq_length)

        mean_val: np.float64 = np.mean(resampled)
        std_val: np.float64 = np.std(resampled) + 1e-8
        normalised: np.ndarray = (resampled - mean_val) / std_val
        
        return normalised.astype(np.float32), coverage, False


# ── Public ECGPreprocessor ───────────────────────────────────────────────────

class ECGPreprocessor:
    """Dual‑input preprocessor: WFDB records and scanned ECG images.

    Returns a 4‑D tensor ``(1, 12, seq_length)`` and a 2‑D float array
    ``(12, seq_length)`` of the normalised raw signals suitable for XAI
    overlays.

    Attributes:
        cfg (Settings): The preprocessor config.
    """

    def __init__(self, cfg: Settings) -> None:
        """Initialises the ECG preprocessor.

        Args:
            cfg (Settings): Preprocessing configuration.
        """
        self.cfg: Settings = cfg
        # Optical pipeline components
        self._remover: _AdaptiveGridRemover = _AdaptiveGridRemover(cfg)
        self._slicer: _ECGGridSlicer = _ECGGridSlicer(cfg)
        self._digitizer: _WaveformDigitizer = _WaveformDigitizer(cfg)

    def process_wfdb(self, file_path: str) -> Tuple[torch.Tensor, np.ndarray]:
        """Read a WFDB ``.dat`` / ``.hea`` pair and normalise."""
        path: Path = Path(file_path)
        base: Path = path.with_suffix('')
        if not path.exists() and not (base.with_suffix('.dat')).exists():
            raise ECGFileReadError(f"ECG record not found: {file_path}")

        sig: np.ndarray
        try:
            sig, _ = wfdb.rdsamp(str(base))
        except Exception as exc:
            raise ECGFileReadError(
                f"Failed to read WFDB record {base}: {exc}"
            ) from exc

        # Z‑score per lead
        mean: np.ndarray = np.mean(sig, axis=0)
        std: np.ndarray = np.std(sig, axis=0) + 1e-6
        normalised: np.ndarray = (sig - mean) / std

        # Truncate to seq_length
        normalised = normalised[: self.cfg.seq_length]

        # (T, 12) -> (12, 500)
        signals_2d: np.ndarray = normalised.T.astype(np.float32)

        if signals_2d.shape[0] != self.cfg.num_leads:
            raise InvalidLeadCountError(f"Expected {self.cfg.num_leads} leads, got {signals_2d.shape[0]}")
        if signals_2d.shape[1] != self.cfg.seq_length:
            raise SignalLengthMismatchError(f"Expected length {self.cfg.seq_length}, got {signals_2d.shape[1]}")

        tensor: torch.Tensor = torch.tensor(signals_2d, dtype=torch.float32).unsqueeze(0)
        return tensor, signals_2d

    def process_image(self, image_path: str, diagnostic_mode: bool = False, diagnostic_out_dir: str = "/app/data/ecg_diagnostics") -> Tuple[torch.Tensor, np.ndarray]:
        """Run the full optical pipeline on a scanned ECG image."""
        # 1. Remove grid adaptively
        binary_img: np.ndarray = self._remover.remove_grid(image_path)
        
        if diagnostic_mode:
            import os
            os.makedirs(diagnostic_out_dir, exist_ok=True)
            cv2.imwrite(os.path.join(diagnostic_out_dir, "grid_removed.png"), binary_img)

        # 2. Slice into 12 lead images
        lead_images: Dict[str, np.ndarray] = self._slicer.slice_image(binary_img)

        # 3. Digitise each lead in standard clinical order
        lead_order: List[str] = [
            'I', 'aVR', 'V1', 'V4',
            'II', 'aVL', 'V2', 'V5',
            'III', 'aVF', 'V3', 'V6',
        ]
        signals_list: List[np.ndarray] = []
        coverages: Dict[str, float] = {}
        span_failures: Dict[str, bool] = {}
        for lead_name in lead_order:
            lead_img: np.ndarray | None = lead_images.get(lead_name)
            if lead_img is None:
                raise SignalProcessingError(
                    f"Lead {lead_name} not found in sliced image"
                )
            
            signal_1d: Optional[np.ndarray]
            cov: float
            span_failed: bool
            signal_1d, cov, span_failed = self._digitizer.extract_1d_signal(lead_img)
            
            if signal_1d is not None:
                signals_list.append(signal_1d)
                
            coverages[lead_name] = cov
            span_failures[lead_name] = span_failed
            
            if diagnostic_mode:
                cv2.imwrite(os.path.join(diagnostic_out_dir, f"lead_{lead_name}.png"), lead_img)
                if signal_1d is not None:
                    np.save(os.path.join(diagnostic_out_dir, f"signal_{lead_name}.npy"), signal_1d)
            
        failed_leads = [
            lead for lead in lead_order 
            if coverages[lead] < 0.90 or span_failures[lead]
        ]
        
        if failed_leads:
            raise ECGExtractionError(
                "This ECG image could not be read reliably.",
                coverage=coverages,
                leads_failed=failed_leads
            )
            
        if len(signals_list) != self.cfg.num_leads:
            raise SignalProcessingError("Not all leads produced a valid signal.")

        signals_2d: np.ndarray = np.stack(signals_list, axis=0).astype(np.float32)

        if signals_2d.shape[0] != self.cfg.num_leads:
            raise InvalidLeadCountError(f"Expected {self.cfg.num_leads} leads, got {signals_2d.shape[0]}")
        if signals_2d.shape[1] != self.cfg.seq_length:
            raise SignalLengthMismatchError(f"Expected length {self.cfg.seq_length}, got {signals_2d.shape[1]}")

        tensor: torch.Tensor = torch.tensor(signals_2d, dtype=torch.float32).unsqueeze(0)
        return tensor, signals_2d