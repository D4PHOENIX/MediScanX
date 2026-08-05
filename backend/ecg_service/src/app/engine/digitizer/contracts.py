from __future__ import annotations
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, tuple, list
import numpy as np
import numpy.typing as npt


@dataclass(frozen=True)
class DigitizationContract:
    """Immutable clinical and numerical contract for optical ECG reconstruction."""

    lead_count: int = 12
    sample_rate_hz: int = 100
    duration_s: float = 2.5
    sequence_length: int = 250
    paper_speed_mm_per_s: float = 25.0
    gain_mm_per_mv: float = 10.0
    calibration_tolerance_fraction: float = 0.05
    minimum_qrs_duration_s: float = 0.060
    minimum_qrs_pixels: int = 5
    analysis_scope: str = "morphology_only"

    @property
    def minimum_pixels_per_mm(self) -> float:
        """Return the geometry-derived resolution floor for a 60 ms QRS complex."""
        qrs_width_mm = self.paper_speed_mm_per_s * self.minimum_qrs_duration_s
        return self.minimum_qrs_pixels / qrs_width_mm


@dataclass(frozen=True)
class EvaluationThresholds:
    """Approved signal-level acceptance thresholds for every required ECG lead."""

    minimum_pearson_r: float = 0.95
    maximum_zscore_nrmse: float = 0.20
    minimum_amplitude_ratio: float = 0.85
    maximum_amplitude_ratio: float = 1.15


LEAD_ORDER: Final[tuple[str, ...]] = (
    "I", "II", "III", "aVR", "aVL", "aVF",
    "V1", "V2", "V3", "V4", "V5", "V6",
)

LEAD_NAME_ALIASES: Final[Mapping[str, str]] = {
    "I": "I",
    "II": "II",
    "III": "III",
    "AVR": "aVR",
    "AVL": "aVL",
    "AVF": "aVF",
    "V1": "V1",
    "V2": "V2",
    "V3": "V3",
    "V4": "V4",
    "V5": "V5",
    "V6": "V6",
}


class DigitizationFailure(Exception):
    """Controlled failure raised when an ECG image is unsafe to digitize."""

    def __init__(self, reason: str) -> None:
        """Store a short machine-readable failure reason."""
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ImageStandardizationConfig:
    """Parameters for color-safe image conversion and adaptive ink detection."""

    minimum_side_px: int = 128
    illumination_sigma_fraction: float = 0.02
    adaptive_window_fraction: float = 0.03
    adaptive_window_min_px: int = 31
    adaptive_window_max_px: int = 251
    adaptive_threshold_c: int = 4
    minimum_ink_fraction: float = 0.0005
    maximum_ink_fraction: float = 0.40


@dataclass(frozen=True)
class StandardizedECGImage:
    """Intermediate image representation used by later geometry stages."""

    source_gray: npt.NDArray[np.uint8]
    illumination_corrected_gray: npt.NDArray[np.uint8]
    initial_ink_mask: npt.NDArray[np.uint8]
    adaptive_window_px: int
    initial_ink_fraction: float


@dataclass(frozen=True)
class GridDetectionConfig:
    """Parameters for colour-independent periodic ECG grid detection."""

    minimum_minor_grid_period_px: float = 3.0
    maximum_dominant_period_px: int = 96
    minimum_peak_correlation: float = 0.05
    minor_lines_per_major_grid: int = 5
    line_refinement_radius_fraction: float = 0.30
    grid_line_half_width_fraction: float = 0.08


@dataclass(frozen=True)
class GridGeometry:
    """Detected 1 mm and 5 mm grid geometry in image-pixel coordinates."""

    vertical_major_period_px: float
    horizontal_major_period_px: float
    vertical_minor_period_px: float
    horizontal_minor_period_px: float
    vertical_minor_grid_positions_px: npt.NDArray[np.int32]
    horizontal_minor_grid_positions_px: npt.NDArray[np.int32]
    grid_line_half_width_px: int
    vertical_period_confidence: float
    horizontal_period_confidence: float


@dataclass(frozen=True)
class GridSuppressionResult:
    """Grid mask and non-grid ink mask produced from adaptive ink detection."""

    geometry: GridGeometry
    periodic_grid_mask: npt.NDArray[np.uint8]
    non_grid_ink_mask: npt.NDArray[np.uint8]
    remaining_ink_fraction: float


PAPER_SPEED_MM_PER_S: float = 25.0
GAIN_MM_PER_MV: float = 10.0
SAMPLE_RATE_HZ: float = 100.0
TARGET_SAMPLES: int = 250
LEAD_DURATION_S: float = 2.5
LEAD_COLUMN_WIDTH_MM: float = 62.5
MIN_RESOLUTION_PX_PER_MM: float = 3.33

REQUIRED_LEADS: tuple[str, ...] = (
    "I", "II", "III", "aVR", "aVL", "aVF",
    "V1", "V2", "V3", "V4", "V5", "V6",
)

STANDARD_LAYOUT: dict[tuple[int, int], str] = {
    (0, 0): "I",   (0, 1): "aVR", (0, 2): "V1", (0, 3): "V4",
    (1, 0): "II",  (1, 1): "aVL", (1, 2): "V2", (1, 3): "V5",
    (2, 0): "III", (2, 1): "aVF", (2, 2): "V3", (2, 3): "V6",
}
