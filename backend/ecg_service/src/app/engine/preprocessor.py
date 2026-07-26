"""Dual-input ECG preprocessing pipeline."""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

import cv2
import numpy as np
import torch
import wfdb
from scipy.interpolate import interp1d
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

class _PinkGridRemover:
    """Removes the pink background grid from a scanned ECG image.

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
        """Process image to remove the pink grid.

        Args:
            image_path (str): File path to the ECG input image.

        Returns:
            np.ndarray: Binary image with the grid removed.

        Raises:
            ECGFileReadError: If the image is not found or fails to read.
        """
        img: np.ndarray = cv2.imread(image_path)
        if img is None:
            raise ECGFileReadError(f"Image not found at path: {image_path}")
        hsv: np.ndarray = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        mask1: np.ndarray = cv2.inRange(hsv,
                                        self.cfg.hsv_lower_pink1,
                                        self.cfg.hsv_upper_pink1)
        mask2: np.ndarray = cv2.inRange(hsv,
                                        self.cfg.hsv_lower_pink2,
                                        self.cfg.hsv_upper_pink2)
        combined: np.ndarray = mask1 | mask2
        ink_mask: np.ndarray = cv2.bitwise_not(combined)
        clean: np.ndarray = np.ones_like(img) * 255
        isolated: np.ndarray = cv2.bitwise_and(img, img, mask=ink_mask)
        isolated[ink_mask == 0] = 255
        gray: np.ndarray = cv2.cvtColor(isolated, cv2.COLOR_BGR2GRAY)
        _: float
        binary: np.ndarray
        _, binary = cv2.threshold(gray, 120, 255, cv2.THRESH_BINARY_INV)
        return binary


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
        """Extract a 1D signal from a binary slice of a lead.

        Args:
            lead_img (np.ndarray): Sliced image for a specific lead.

        Returns:
            Tuple[Optional[np.ndarray], float, bool]: The normalised 1D signal array (or None if failed), fractional coverage, and boolean flag if span fails.
        """
        height: int
        width: int
        height, width = lead_img.shape
        y_indices: np.ndarray
        x_indices: np.ndarray
        y_indices, x_indices = np.where(lead_img == 255)

        col_counts: np.ndarray = np.bincount(x_indices, minlength=width)
        valid_cols: np.ndarray = col_counts > 0
        coverage: float = float(np.sum(valid_cols) / width)
        
        if np.sum(valid_cols) < 2:
            return None, coverage, True

        y_sums: np.ndarray = np.bincount(x_indices, weights=y_indices, minlength=width)
        y_centers: np.ndarray = y_sums[valid_cols] / col_counts[valid_cols]
        amplitudes: np.ndarray = height - y_centers
        valid_x_arr: np.ndarray = np.where(valid_cols)[0].astype(np.float32)
        raw: np.ndarray = amplitudes.astype(np.float32)

        x_min = valid_x_arr[0]
        x_max = valid_x_arr[-1]
        span_fraction = (x_max - x_min + 1) / width
        
        # Genuine span check: reject if the trace spans less than 50% of the box width
        if span_fraction < 0.5:
            return None, coverage, True

        eval_x: np.ndarray = np.linspace(x_min, x_max, int(x_max - x_min + 1), dtype=np.float32)
        interpolator: interp1d = interp1d(valid_x_arr, raw, kind='linear')
        interpolated: np.ndarray = interpolator(eval_x)

        resampled: np.ndarray = resample(interpolated, self.cfg.seq_length)

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
        self._remover: _PinkGridRemover = _PinkGridRemover(cfg)
        self._slicer: _ECGGridSlicer = _ECGGridSlicer(cfg)
        self._digitizer: _WaveformDigitizer = _WaveformDigitizer(cfg)

    def _write_diagnostic(self, relative_name: str, payload: np.ndarray) -> None:
        """Helper to write diagnostic files without propagating exceptions."""
        if getattr(self, '_diagnostics_failed', False):
            return
        try:
            os.makedirs(self.cfg.ecg_diagnostic_dir, exist_ok=True)
            out_path = os.path.join(self.cfg.ecg_diagnostic_dir, relative_name)
            if out_path.endswith('.npy'):
                np.save(out_path, payload)
            else:
                cv2.imwrite(out_path, payload)
        except Exception as exc:
            logger.warning(f"Failed to write diagnostic file {relative_name}: {exc}")
            self._diagnostics_failed = True

    def process_wfdb(self, file_path: str) -> Tuple[torch.Tensor, np.ndarray]:
        """Read a WFDB ``.dat`` / ``.hea`` pair and normalise.

        Args:
            file_path (str): File path to the WFDB record.

        Returns:
            Tuple[torch.Tensor, np.ndarray]: A tuple containing the tensor
                of shape ``(1, 12, 500)`` and raw signal array of shape ``(12, 500)``.

        Raises:
            ECGFileReadError: If the file path does not point to a valid record.
            InvalidLeadCountError: If the read signals have incorrect lead counts.
            SignalLengthMismatchError: If the processed signal length is invalid.
        """
        path: Path = Path(file_path)
        # wfdb.rdsamp expects the base name without extension
        base: Path = path.with_suffix('')
        if not path.exists() and not (base.with_suffix('.dat')).exists():
            raise ECGFileReadError(f"ECG record not found: {file_path}")

        sig: np.ndarray
        _: Any
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

    def process_image(self, image_path: str, diagnostic_mode: bool = False) -> Tuple[torch.Tensor, np.ndarray]:
        """Run the full optical pipeline on a scanned ECG image.

        Args:
            image_path (str): Path to the scanned image.

        Returns:
            Tuple[torch.Tensor, np.ndarray]: A tuple containing the tensor
                of shape ``(1, 12, 500)`` and raw signal array of shape ``(12, 500)``.

        Raises:
            SignalProcessingError: If optical extraction fails.
            InvalidLeadCountError: If incorrect number of leads extracted.
            SignalLengthMismatchError: If the expected length doesn't match.
        """
        eff_diagnostic_mode = diagnostic_mode or self.cfg.ecg_diagnostic_mode
        self._diagnostics_failed = False

        # 1. Remove pink grid
        binary_img: np.ndarray = self._remover.remove_grid(image_path)
        
        if eff_diagnostic_mode:
            self._write_diagnostic("grid_removed.png", binary_img)

        # 2. Slice into 12 lead images
        lead_images: Dict[str, np.ndarray] = self._slicer.slice_image(binary_img)

        # 3. Digitise each lead in standard clinical order
        lead_order: List[str] = [
            'I', 'aVR', 'V1', 'V4',
            'II', 'aVL', 'V2', 'V5',
            'III', 'aVF', 'V3', 'V6',
        ]
        signals_list: List[np.ndarray] = []
        lead_name: str
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
            
            if eff_diagnostic_mode:
                self._write_diagnostic(f"lead_{lead_name}.png", lead_img)
                if signal_1d is not None:
                    self._write_diagnostic(f"signal_{lead_name}.npy", signal_1d)
            
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
