from __future__ import annotations
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final
import cv2
import numpy as np
import numpy.typing as npt
from scipy import ndimage
from scipy.signal import correlate, find_peaks
from scipy.interpolate import PchipInterpolator



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


class ImageStandardizer:
    """Standardize real-world ECG images without any grid-color dependency."""

    def __init__(self, config: ImageStandardizationConfig) -> None:
        """Initialize image-quality and adaptive-threshold settings."""
        self.config = config

    def standardize(self, image: np.ndarray) -> StandardizedECGImage:
        """Convert an input ECG image into corrected grayscale and an ink mask."""
        source_gray = self._to_grayscale_uint8(image)
        height_px, width_px = source_gray.shape

        if min(height_px, width_px) < self.config.minimum_side_px:
            raise DigitizationFailure("image_too_small_for_analysis")

        illumination_sigma_px = max(
            3.0,
            min(height_px, width_px) * self.config.illumination_sigma_fraction,
        )

        background = cv2.GaussianBlur(
            source_gray,
            ksize=(0, 0),
            sigmaX=illumination_sigma_px,
            sigmaY=illumination_sigma_px,
        )
        background = np.maximum(background, 1).astype(np.uint8)

        illumination_corrected_gray = cv2.divide(
            source_gray,
            background,
            scale=255.0,
        )

        adaptive_window_px = self._adaptive_window_px(
            image_height_px=height_px,
            image_width_px=width_px,
        )

        initial_ink_mask = cv2.adaptiveThreshold(
            illumination_corrected_gray,
            maxValue=255,
            adaptiveMethod=cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            thresholdType=cv2.THRESH_BINARY_INV,
            blockSize=adaptive_window_px,
            C=self.config.adaptive_threshold_c,
        )

        initial_ink_fraction = float(
            np.count_nonzero(initial_ink_mask) / initial_ink_mask.size
        )

        if initial_ink_fraction < self.config.minimum_ink_fraction:
            raise DigitizationFailure("insufficient_detectable_ink")

        if initial_ink_fraction > self.config.maximum_ink_fraction:
            raise DigitizationFailure("excessive_detected_ink")

        return StandardizedECGImage(
            source_gray=source_gray,
            illumination_corrected_gray=illumination_corrected_gray,
            initial_ink_mask=initial_ink_mask,
            adaptive_window_px=adaptive_window_px,
            initial_ink_fraction=initial_ink_fraction,
        )

    def _to_grayscale_uint8(self, image: np.ndarray) -> npt.NDArray[np.uint8]:
        """Convert grayscale, BGR, RGB, or RGBA input into order-invariant grayscale."""
        image_array = np.asarray(image)

        if image_array.size == 0:
            raise DigitizationFailure("empty_image")

        if image_array.ndim == 2:
            return self._to_uint8(image_array)

        if image_array.ndim != 3 or image_array.shape[2] not in (3, 4):
            raise DigitizationFailure("unsupported_image_shape")

        converted_image = self._to_uint8(image_array)
        color_channels = converted_image[:, :, :3].astype(np.float32)

        if converted_image.shape[2] == 4:
            alpha = converted_image[:, :, 3:4].astype(np.float32) / 255.0
            color_channels = color_channels * alpha + 255.0 * (1.0 - alpha)

        # Channel mean is intentionally invariant to BGR versus RGB ordering.
        grayscale = np.rint(np.mean(color_channels, axis=2)).astype(np.uint8)
        return grayscale

    def _to_uint8(self, image: np.ndarray) -> npt.NDArray[np.uint8]:
        """Convert a finite non-negative numeric image into the uint8 range."""
        if not np.issubdtype(image.dtype, np.number):
            raise DigitizationFailure("non_numeric_image")

        if not np.isfinite(image).all():
            raise DigitizationFailure("image_contains_nan_or_inf")

        image_float = image.astype(np.float32)

        if float(image_float.min()) < 0.0:
            raise DigitizationFailure("negative_image_values")

        maximum_value = float(image_float.max())

        if maximum_value <= 1.0:
            scaled_image = image_float * 255.0
        elif maximum_value <= 255.0:
            scaled_image = image_float
        elif np.issubdtype(image.dtype, np.integer):
            dtype_maximum = float(np.iinfo(image.dtype).max)
            scaled_image = image_float * (255.0 / dtype_maximum)
        else:
            raise DigitizationFailure("unsupported_float_image_range")

        return np.rint(np.clip(scaled_image, 0.0, 255.0)).astype(np.uint8)

    def _adaptive_window_px(
        self,
        image_height_px: int,
        image_width_px: int,
    ) -> int:
        """Return a bounded odd adaptive-threshold window derived from image size."""
        raw_window_px = int(
            round(
                min(image_height_px, image_width_px)
                * self.config.adaptive_window_fraction
            )
        )

        bounded_window_px = min(
            max(raw_window_px, self.config.adaptive_window_min_px),
            self.config.adaptive_window_max_px,
        )

        return (
            bounded_window_px
            if bounded_window_px % 2 == 1
            else bounded_window_px + 1
        )


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


class PeriodicGridSuppressor:
    """Suppress periodic ECG grid pixels without relying on grid colour."""

    def __init__(self, config: GridDetectionConfig) -> None:
        """Initialize periodic-grid detection settings."""
        self.config = config

    def suppress(self, initial_ink_mask: np.ndarray) -> GridSuppressionResult:
        """Detect 1 mm grid positions and remove only those periodic pixels."""
        if initial_ink_mask.ndim != 2:
            raise DigitizationFailure("grid_detection_requires_grayscale_mask")

        binary_mask = (initial_ink_mask > 0).astype(np.uint8)
        image_height_px, image_width_px = binary_mask.shape

        vertical_projection = binary_mask.sum(axis=0).astype(np.float64)
        horizontal_projection = binary_mask.sum(axis=1).astype(np.float64)

        dominant_vertical_period_px, vertical_confidence = (
            self._detect_dominant_period(vertical_projection)
        )
        dominant_horizontal_period_px, horizontal_confidence = (
            self._detect_dominant_period(horizontal_projection)
        )

        vertical_major_period_px, vertical_minor_period_px = (
            self._resolve_major_and_minor_periods(dominant_vertical_period_px)
        )
        horizontal_major_period_px, horizontal_minor_period_px = (
            self._resolve_major_and_minor_periods(dominant_horizontal_period_px)
        )

        vertical_seed_phase_px = self._detect_phase(
            projection=vertical_projection,
            period_px=dominant_vertical_period_px,
        )
        horizontal_seed_phase_px = self._detect_phase(
            projection=horizontal_projection,
            period_px=dominant_horizontal_period_px,
        )

        vertical_minor_positions_px = self._refine_grid_line_positions(
            projection=vertical_projection,
            seed_phase_px=vertical_seed_phase_px,
            minor_period_px=vertical_minor_period_px,
        )
        horizontal_minor_positions_px = self._refine_grid_line_positions(
            projection=horizontal_projection,
            seed_phase_px=horizontal_seed_phase_px,
            minor_period_px=horizontal_minor_period_px,
        )

        grid_line_half_width_px = max(
            1,
            int(
                round(
                    min(vertical_minor_period_px, horizontal_minor_period_px)
                    * self.config.grid_line_half_width_fraction
                )
            ),
        )

        geometry = GridGeometry(
            vertical_major_period_px=vertical_major_period_px,
            horizontal_major_period_px=horizontal_major_period_px,
            vertical_minor_period_px=vertical_minor_period_px,
            horizontal_minor_period_px=horizontal_minor_period_px,
            vertical_minor_grid_positions_px=vertical_minor_positions_px,
            horizontal_minor_grid_positions_px=horizontal_minor_positions_px,
            grid_line_half_width_px=grid_line_half_width_px,
            vertical_period_confidence=vertical_confidence,
            horizontal_period_confidence=horizontal_confidence,
        )

        periodic_grid_mask = self._build_grid_mask(
            image_height_px=image_height_px,
            image_width_px=image_width_px,
            geometry=geometry,
        )

        non_grid_ink_mask = cv2.bitwise_and(
            initial_ink_mask,
            cv2.bitwise_not(periodic_grid_mask),
        )

        remaining_ink_fraction = float(
            np.count_nonzero(non_grid_ink_mask) / non_grid_ink_mask.size
        )

        if remaining_ink_fraction <= 0.0:
            raise DigitizationFailure("grid_suppression_removed_all_ink")

        return GridSuppressionResult(
            geometry=geometry,
            periodic_grid_mask=periodic_grid_mask,
            non_grid_ink_mask=non_grid_ink_mask,
            remaining_ink_fraction=remaining_ink_fraction,
        )

    def _detect_dominant_period(
        self,
        projection: npt.NDArray[np.float64],
    ) -> tuple[int, float]:
        """Detect the strongest periodic interval, usually the 5 mm major grid."""
        if projection.ndim != 1 or projection.size < 32:
            raise DigitizationFailure("projection_too_short_for_grid_detection")

        centered_projection = projection - np.mean(projection)
        if np.allclose(centered_projection, 0.0):
            raise DigitizationFailure("no_projection_variation_for_grid_detection")

        autocorrelation = correlate(
            centered_projection,
            centered_projection,
            mode="full",
            method="fft",
        )[projection.size - 1:]

        zero_lag_value = float(autocorrelation[0])
        if zero_lag_value <= 0.0:
            raise DigitizationFailure("invalid_grid_autocorrelation")

        normalized_autocorrelation = autocorrelation / zero_lag_value

        maximum_lag_px = min(
            self.config.maximum_dominant_period_px,
            projection.size // 4,
        )
        minimum_lag_px = int(
            np.ceil(
                self.config.minimum_minor_grid_period_px
                * self.config.minor_lines_per_major_grid
            )
        )

        if maximum_lag_px <= minimum_lag_px:
            raise DigitizationFailure("image_too_small_for_grid_period_detection")

        candidate_region = normalized_autocorrelation[
            minimum_lag_px : maximum_lag_px + 1
        ]

        peak_indices, _ = find_peaks(candidate_region)

        candidate_periods = [
            int(peak_index + minimum_lag_px)
            for peak_index in peak_indices
            if normalized_autocorrelation[peak_index + minimum_lag_px]
            >= self.config.minimum_peak_correlation
        ]

        if not candidate_periods:
            raise DigitizationFailure("periodic_major_grid_not_detected")

        def periodic_support(period_px: int) -> float:
            """Score autocorrelation agreement across repeated major-grid intervals."""
            multiples = np.arange(
                period_px,
                maximum_lag_px + 1,
                period_px,
                dtype=np.int32,
            )
            return float(np.mean(normalized_autocorrelation[multiples]))

        best_period_px = max(
            candidate_periods,
            key=lambda period_px: (periodic_support(period_px), -period_px),
        )

        return (
            best_period_px,
            float(normalized_autocorrelation[best_period_px]),
        )

    def _resolve_major_and_minor_periods(
        self,
        dominant_period_px: int,
    ) -> tuple[float, float]:
        """Convert a detected 5 mm major-grid interval into the 1 mm interval."""
        minor_period_px = (
            float(dominant_period_px) / self.config.minor_lines_per_major_grid
        )

        if minor_period_px < self.config.minimum_minor_grid_period_px:
            raise DigitizationFailure("minor_grid_resolution_below_physical_floor")

        return float(dominant_period_px), minor_period_px

    def _detect_phase(
        self,
        projection: npt.NDArray[np.float64],
        period_px: int,
    ) -> int:
        """Find the offset where repeated dominant grid lines best fit a projection."""
        phase_scores = np.empty(period_px, dtype=np.float64)

        for phase_px in range(period_px):
            phase_samples = projection[phase_px::period_px]
            phase_scores[phase_px] = float(np.mean(phase_samples))

        return int(np.argmax(phase_scores))

    def _refine_grid_line_positions(
        self,
        projection: npt.NDArray[np.float64],
        seed_phase_px: int,
        minor_period_px: float,
    ) -> npt.NDArray[np.int32]:
        """Snap each expected 1 mm grid line to the strongest nearby projection peak."""
        refinement_radius_px = max(
            1,
            int(round(minor_period_px * self.config.line_refinement_radius_fraction)),
        )

        first_expected_position_px = float(seed_phase_px)
        while first_expected_position_px > 0.0:
            first_expected_position_px -= minor_period_px

        expected_positions_px = np.arange(
            first_expected_position_px,
            projection.size + minor_period_px,
            minor_period_px,
            dtype=np.float64,
        )

        refined_positions: list[int] = []

        for expected_position_px in expected_positions_px:
            centre_px = int(round(expected_position_px))
            lower_bound_px = max(0, centre_px - refinement_radius_px)
            upper_bound_px = min(
                projection.size - 1,
                centre_px + refinement_radius_px,
            )

            if lower_bound_px > upper_bound_px:
                continue

            local_projection = projection[
                lower_bound_px : upper_bound_px + 1
            ]
            refined_position_px = (
                lower_bound_px + int(np.argmax(local_projection))
            )
            refined_positions.append(refined_position_px)

        unique_positions = np.unique(
            np.asarray(refined_positions, dtype=np.int32)
        )

        if unique_positions.size < 6:
            raise DigitizationFailure("insufficient_minor_grid_lines_detected")

        observed_intervals_px = np.diff(unique_positions).astype(np.float64)
        median_interval_px = float(np.median(observed_intervals_px))

        if not np.isclose(
            median_interval_px,
            minor_period_px,
            rtol=0.35,
            atol=1.0,
        ):
            raise DigitizationFailure("inconsistent_minor_grid_spacing")

        return unique_positions

    def _build_grid_mask(
        self,
        image_height_px: int,
        image_width_px: int,
        geometry: GridGeometry,
    ) -> npt.NDArray[np.uint8]:
        """Construct a grid mask using refined 1 mm line locations."""
        grid_mask = np.zeros((image_height_px, image_width_px), dtype=np.uint8)
        line_thickness_px = 2 * geometry.grid_line_half_width_px + 1

        for x_position in geometry.vertical_minor_grid_positions_px:
            cv2.line(
                grid_mask,
                (int(x_position), 0),
                (int(x_position), image_height_px - 1),
                color=255,
                thickness=line_thickness_px,
                lineType=cv2.LINE_8,
            )

        for y_position in geometry.horizontal_minor_grid_positions_px:
            cv2.line(
                grid_mask,
                (0, int(y_position)),
                (image_width_px - 1, int(y_position)),
                color=255,
                thickness=line_thickness_px,
                lineType=cv2.LINE_8,
            )

        return grid_mask


PAPER_SPEED_MM_PER_S:     float = 25.0
GAIN_MM_PER_MV:           float = 10.0
SAMPLE_RATE_HZ:           float = 100.0
TARGET_SAMPLES:           int   = 250
LEAD_DURATION_S:          float = 2.5
LEAD_COLUMN_WIDTH_MM:     float = 62.5
MIN_RESOLUTION_PX_PER_MM: float = 3.33

REQUIRED_LEADS: tuple[str, ...] = (
    "I", "II", "III", "aVR", "aVL", "aVF",
    "V1", "V2", "V3", "V4", "V5", "V6",
)

STANDARD_LAYOUT: dict[tuple[int, int], str] = {
    (0, 0): "I",    (0, 1): "aVR", (0, 2): "V1", (0, 3): "V4",
    (1, 0): "II",   (1, 1): "aVL", (1, 2): "V2", (1, 3): "V5",
    (2, 0): "III",  (2, 1): "aVF", (2, 2): "V3", (2, 3): "V6",
}

def derive_px_per_mm(geometry) -> float:
    v_px = float(geometry.vertical_minor_period_px)
    h_px = float(geometry.horizontal_minor_period_px)

    if v_px <= 0.0 or h_px <= 0.0:
        raise ValueError(f"Invalid minor grid period: V={v_px}, H={h_px}")

    disagreement = abs(v_px - h_px) / ((v_px + h_px) / 2.0)
    if disagreement > 0.35:
        raise ValueError(
            f"Anisotropic scale error: V={v_px:.3f}px and H={h_px:.3f}px "
            f"disagree by {disagreement:.2%} (> 35%)"
        )
    return float(np.sqrt(v_px * h_px))

@dataclass
class PerspectiveRectifyConfig:
    aspect_ratio_tolerance:  float = 0.15
    min_paper_area_fraction: float = 0.30
    approx_epsilon_fraction: float = 0.02

class PerspectiveRectifier:
    def __init__(self, config: PerspectiveRectifyConfig | None = None) -> None:
        self.config = config or PerspectiveRectifyConfig()

    def rectify(
        self, image: np.ndarray, px_per_mm_hint: float | None = None
    ) -> tuple[np.ndarray, bool, str | None]:
        h_img, w_img = image.shape[:2]
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image.copy()

        ys, xs = np.where(gray < 240)
        if ys.size == 0:
            return image, False, "No ink detected"

        pts = np.column_stack((xs, ys)).astype(np.float32)
        (cx, cy), (rw, rh), angle = cv2.minAreaRect(pts)
        skew_deg = (90.0 - angle) if rw < rh else (-angle)

        if abs(skew_deg) > 0.5 and abs(skew_deg) < 45.0:
            M = cv2.getRotationMatrix2D((w_img // 2, h_img // 2), -skew_deg, 1.0)
            rectified = cv2.warpAffine(image, M, (w_img, h_img), borderValue=(255, 255, 255))
            return rectified, True, None

        return image, False, None

@dataclass
class BandGeometryConfig:
    smoothing_sigma_mm:         float = 5.0
    min_band_height_fraction:   float = 0.08
    max_band_height_fraction:   float = 0.45
    header_exclusion_fraction:  float = 0.08
    footer_exclusion_fraction:  float = 0.05
    expected_band_counts:       tuple[int, ...] = (3, 4)
    min_peak_distance_fraction: float = 0.15
    peak_prominence_fraction:   float = 0.25
    cal_pulse_height_mm:        float = 10.0
    cal_pulse_width_mm:         float = 5.0
    cal_pulse_tolerance:        float = 0.20
    cal_search_width_fraction:  float = 0.15
    min_resolution_px_per_mm:   float = MIN_RESOLUTION_PX_PER_MM

class AdaptiveBandDetector:
    def __init__(self, config: BandGeometryConfig | None = None) -> None:
        self.config = config or BandGeometryConfig()

    def detect(self, non_grid_ink_mask: np.ndarray, px_per_mm: float):
        H, W  = non_grid_ink_mask.shape[:2]
        cfg   = self.config

        content_top_y    = int(H * cfg.header_exclusion_fraction)
        content_bottom_y = int(H * (1.0 - cfg.footer_exclusion_fraction))
        content_mask     = non_grid_ink_mask[content_top_y:content_bottom_y, :]
        content_H        = content_bottom_y - content_top_y

        proj_content = (content_mask > 0).astype(np.float64).sum(axis=1) / float(W)
        sigma_px         = max(cfg.smoothing_sigma_mm * px_per_mm, 8.0)
        smoothed_content = ndimage.gaussian_filter1d(proj_content, sigma=sigma_px)

        full_proj     = np.zeros(H, dtype=np.float64)
        full_smoothed = np.zeros(H, dtype=np.float64)
        full_proj[content_top_y:content_bottom_y]     = proj_content
        full_smoothed[content_top_y:content_bottom_y] = smoothed_content

        peak_max = float(smoothed_content.max())
        if peak_max <= 0:
            return [], content_top_y, content_bottom_y, full_proj, full_smoothed, 0.0, "Band detection failed: No ink found"

        min_peak_dist_px    = int(content_H * cfg.min_peak_distance_fraction)
        min_peak_height     = peak_max * 0.10
        min_peak_prominence = peak_max * cfg.peak_prominence_fraction

        peaks, _ = find_peaks(
            smoothed_content,
            distance=min_peak_dist_px,
            height=min_peak_height,
            prominence=min_peak_prominence,
        )

        if len(peaks) not in cfg.expected_band_counts:
            return [], content_top_y, content_bottom_y, full_proj, full_smoothed, min_peak_height, f"Band detection failed: Detected {len(peaks)} bands; expected {cfg.expected_band_counts}"

        band_rois = []
        for i, peak in enumerate(peaks):
            left  = 0 if i == 0 else (peaks[i - 1] + peak) // 2
            right = content_H if i == len(peaks) - 1 else (peak + peaks[i + 1]) // 2

            h_frac = (right - left) / float(H)
            if cfg.min_band_height_fraction <= h_frac <= cfg.max_band_height_fraction:
                band_rois.append((content_top_y + left, content_top_y + right))

        if len(band_rois) not in cfg.expected_band_counts:
            return [], content_top_y, content_bottom_y, full_proj, full_smoothed, min_peak_height, f"Band detection failed: Detected {len(band_rois)} valid bands; expected {cfg.expected_band_counts}"

        return band_rois, content_top_y, content_bottom_y, full_proj, full_smoothed, min_peak_height, None

@dataclass
class CalibrationPulseResult:
    band_index:       int
    detected:         bool
    height_px:        float
    width_px:         float
    height_mm:        float
    width_mm:         float
    height_error_pct: float
    width_error_pct:  float
    passed:           bool
    failure_reason:   str | None
    bbox:             tuple[int, int, int, int] | None = None

@dataclass
class BandGeometryResult:
    ok:                    bool
    failure_reason:        str | None
    band_rois:             list[tuple[int, int]]
    band_heights_mm:       list[float]
    n_bands:               int
    content_top_y:         int
    content_bottom_y:      int
    calibration_pulses:    list[CalibrationPulseResult]
    calibration_ok:        bool
    px_per_mm:             float
    resolution_ok:         bool
    horizontal_projection: np.ndarray
    smoothed_projection:   np.ndarray
    projection_threshold:  float

class CalibrationVerifier:
    def __init__(self, config: BandGeometryConfig | None = None) -> None:
        self.config = config or BandGeometryConfig()

    def verify_all(
        self, mask: np.ndarray, band_rois: list[tuple[int, int]], px_per_mm: float
    ) -> list[CalibrationPulseResult]:
        return [self._verify_one(mask, idx, roi, px_per_mm) for idx, roi in enumerate(band_rois)]

    def _verify_one(
        self, mask: np.ndarray, band_idx: int, roi: tuple[int, int], px_per_mm: float
    ) -> CalibrationPulseResult:
        cfg          = self.config
        top_y, bot_y = roi
        img_W        = mask.shape[1]
        tol          = cfg.cal_pulse_tolerance

        search_left = int(round(img_W * (1.0 - cfg.cal_search_width_fraction)))
        band_mask   = mask[top_y:bot_y, search_left:]

        def _fail(reason: str) -> CalibrationPulseResult:
            return CalibrationPulseResult(
                band_index=band_idx, detected=False, height_px=0, width_px=0,
                height_mm=0, width_mm=0, height_error_pct=0, width_error_pct=0,
                passed=False, failure_reason=reason
            )

        kernel_v    = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 15))
        closed_mask = cv2.morphologyEx((band_mask > 0).astype(np.uint8), cv2.MORPH_CLOSE, kernel_v)
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(closed_mask)

        bars = []
        for i in range(1, num_labels):
            bx, by, bw, bh, area = stats[i]
            h_mm = bh / px_per_mm
            if 5.0 <= h_mm <= 16.0:
                bars.append({"x": bx, "y": by, "h": bh, "w": bw, "h_mm": h_mm})

        bars.sort(key=lambda item: item["x"])

        found_pair = None
        for i in range(len(bars)):
            for j in range(i + 1, min(i + 5, len(bars))):
                b1, b2  = bars[i], bars[j]
                sep_mm  = (b2["x"] - b1["x"]) / px_per_mm
                sep_err = (sep_mm - cfg.cal_pulse_width_mm) / cfg.cal_pulse_width_mm * 100.0
                avg_h_mm = (b1["h_mm"] + b2["h_mm"]) / 2.0
                h_err   = (avg_h_mm - cfg.cal_pulse_height_mm) / cfg.cal_pulse_height_mm * 100.0

                if abs(sep_err) <= tol * 100.0 and abs(h_err) <= tol * 100.0:
                    found_pair = (b1, b2, sep_mm, avg_h_mm, sep_err, h_err)
                    break
            if found_pair:
                break

        if not found_pair:
            return _fail(f"Band {band_idx}: Calibration pulse twin vertical legs not found")

        b1, b2, sep_mm, avg_h_mm, sep_err, h_err = found_pair
        bbox = (
            search_left + b1["x"],
            top_y + min(b1["y"], b2["y"]),
            (b2["x"] - b1["x"]) + b2["w"],
            int(avg_h_mm * px_per_mm)
        )

        return CalibrationPulseResult(
            band_index=band_idx, detected=True, height_px=avg_h_mm * px_per_mm,
            width_px=sep_mm * px_per_mm, height_mm=avg_h_mm, width_mm=sep_mm,
            height_error_pct=h_err, width_error_pct=sep_err, passed=True,
            failure_reason=None, bbox=bbox,
        )

@dataclass
class TraceExtractionConfig:
    label_exclusion_mm:           float = 7.0
    cal_pulse_margin_mm:          float = 9.4
    max_gap_samples:              int   = 10
    gap_ink_distance_threshold_mm: float = 1.5
    max_jump_mm:                  float = 3.0
    continuity_weight_mm2:        float = 0.05
    min_coverage:                 float = 0.65
    baseline_smoothing_sigma:     float = 2.0
    interpolation_margin_s:       float = 0.05

@dataclass
class LeadExtractionResult:
    lead_name:               str
    ok:                      bool
    signal:                  np.ndarray | None
    coverage:                float
    max_gap_samples_observed: int
    baseline_y_px:           float | None
    failure_reason:          str | None
    trace_y_px:              np.ndarray | None = None

class LeadCropMapper:
    def __init__(self, band_geometry: BandGeometryResult, config: TraceExtractionConfig | None = None) -> None:
        self.bg  = band_geometry
        self.cfg = config or TraceExtractionConfig()

    def map_all_leads(self, image_width: int) -> tuple[dict[str, tuple[int, int, int, int]] | None, str | None]:
        px  = self.bg.px_per_mm
        cfg = self.cfg

        cal_left_xs = [cr.bbox[0] for cr in self.bg.calibration_pulses if cr.passed and cr.bbox is not None]
        if cal_left_xs:
            content_right_x = min(cal_left_xs) - round(cfg.cal_pulse_margin_mm * px)
        else:
            content_right_x = round(image_width - 25.0 * px)

        col_width_px     = LEAD_COLUMN_WIDTH_MM * px
        content_width_px = 4.0 * col_width_px
        content_left_x   = content_right_x - content_width_px

        if content_left_x < 0 or content_right_x > image_width:
            content_left_x  = round(10.0 * px)
            content_right_x = content_left_x + content_width_px

        label_excl_px = round(cfg.label_exclusion_mm * px)
        crops = {}

        for (row_idx, col_idx), lead_name in STANDARD_LAYOUT.items():
            if row_idx >= self.bg.n_bands:
                continue
            top_y, bot_y = self.bg.band_rois[row_idx]
            col_left     = int(round(content_left_x + col_idx * col_width_px))
            col_right    = int(round(content_left_x + (col_idx + 1) * col_width_px))
            trace_left   = max(col_left + label_excl_px, 0)
            col_right    = min(col_right, image_width)

            if trace_left >= col_right:
                return None, f"Lead {lead_name} crop region invalid"

            crops[lead_name] = (top_y, bot_y, trace_left, col_right)

        return crops, None


class ContinuousTraceExtractor:
    def __init__(self, config: TraceExtractionConfig | None = None) -> None:
        self.cfg = config or TraceExtractionConfig()

    def extract_all_leads(
        self, non_grid_ink_mask: np.ndarray,
        lead_crops: dict[str, tuple[int, int, int, int]],
        band_geometry: BandGeometryResult
    ) -> dict[str, LeadExtractionResult]:
        px      = band_geometry.px_per_mm
        results = {}
        for lead_name in REQUIRED_LEADS:
            if lead_name not in lead_crops:
                results[lead_name] = LeadExtractionResult(
                    lead_name=lead_name, ok=False, signal=None, coverage=0.0,
                    max_gap_samples_observed=0, baseline_y_px=None,
                    failure_reason="Missing crop"
                )
                continue
            t_y, b_y, l_x, r_x = lead_crops[lead_name]
            lead_mask = non_grid_ink_mask[t_y:b_y, l_x:r_x]
            results[lead_name] = self._extract_one(lead_name, lead_mask, b_y - t_y, px)
        return results

    def _extract_one(self, lead_name: str, lead_mask: np.ndarray, band_h: int, px_per_mm: float) -> LeadExtractionResult:
        cfg = self.cfg
        if lead_mask.size == 0:
            return LeadExtractionResult(
                lead_name=lead_name, ok=False, signal=None, coverage=0,
                max_gap_samples_observed=0, baseline_y_px=None, failure_reason="Empty mask"
            )

        H, W           = lead_mask.shape
        max_jump_px    = round(cfg.max_jump_mm * px_per_mm)
        max_gap_px     = round(cfg.max_gap_samples * px_per_mm * PAPER_SPEED_MM_PER_S / SAMPLE_RATE_HZ)
        gap_ink_thresh = cfg.gap_ink_distance_threshold_mm * px_per_mm
        alpha_px       = cfg.continuity_weight_mm2 / (px_per_mm ** 2)

        trace_y  = self._viterbi_dp(lead_mask, max_jump_px, alpha_px)
        dist_map = cv2.distanceTransform(
            (lead_mask == 0).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_5
        ).astype(np.float64)
        gap_mask = dist_map[trace_y, np.arange(W)] > gap_ink_thresh

        coverage = float((~gap_mask).sum()) / float(W)
        if coverage < cfg.min_coverage:
            return LeadExtractionResult(
                lead_name=lead_name, ok=False, signal=None, coverage=coverage,
                max_gap_samples_observed=0, baseline_y_px=None,
                failure_reason=f"Coverage {coverage:.1%} < {cfg.min_coverage:.0%}",
                trace_y_px=trace_y
            )

        labeled_gaps, n_gaps = ndimage.label(gap_mask.astype(np.int32))
        max_gap_cols        = max(
            [int((labeled_gaps == g).sum()) for g in range(1, n_gaps + 1)], default=0
        )
        px_per_sample       = px_per_mm * PAPER_SPEED_MM_PER_S / SAMPLE_RATE_HZ
        max_gap_samples_obs = int(round(max_gap_cols / px_per_sample))

        valid_ys        = trace_y[~gap_mask]
        counts, edges   = np.histogram(valid_ys, bins=max(band_h // 2, 20), range=(0, band_h))
        smoothed_counts = ndimage.gaussian_filter1d(counts.astype(float), sigma=cfg.baseline_smoothing_sigma)
        baseline_y      = float(
            (edges[np.argmax(smoothed_counts)] + edges[np.argmax(smoothed_counts) + 1]) / 2.0
        )

        if max_gap_cols > max_gap_px:
            return LeadExtractionResult(
                lead_name=lead_name, ok=False, signal=None, coverage=coverage,
                max_gap_samples_observed=max_gap_samples_obs, baseline_y_px=baseline_y,
                failure_reason=f"Max gap {max_gap_cols}px > {max_gap_px}px", trace_y_px=trace_y
            )

        t_px     = np.arange(W) / (px_per_mm * PAPER_SPEED_MM_PER_S)
        valid_t  = t_px[~gap_mask]
        valid_mv = (baseline_y - trace_y[~gap_mask]) / (px_per_mm * GAIN_MM_PER_MV)

        t_target = np.linspace(valid_t[0], valid_t[-1], TARGET_SAMPLES)
        interp   = PchipInterpolator(valid_t, valid_mv, extrapolate=False)
        sig_250  = interp(t_target)

        if np.any(np.isnan(sig_250)) or not np.all(np.isfinite(sig_250)):
            return LeadExtractionResult(
                lead_name=lead_name, ok=False, signal=None, coverage=coverage,
                max_gap_samples_observed=max_gap_samples_obs, baseline_y_px=baseline_y,
                failure_reason="Interpolation produced NaN/Inf", trace_y_px=trace_y
            )

        return LeadExtractionResult(
            lead_name=lead_name, ok=True, signal=sig_250.astype(np.float32),
            coverage=coverage, max_gap_samples_observed=max_gap_samples_obs,
            baseline_y_px=baseline_y, failure_reason=None, trace_y_px=trace_y
        )

    def _viterbi_dp(self, mask: np.ndarray, max_jump_px: int, alpha_px: float) -> np.ndarray:
        H, W     = mask.shape
        INF      = 1e9
        dist_map = cv2.distanceTransform(
            (mask == 0).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_5
        ).astype(np.float64)

        pad          = max_jump_px
        win          = 2 * pad + 1
        delta        = np.arange(-pad, pad + 1, dtype=np.float64)
        trans_kernel = alpha_px * (delta ** 2)

        backptrs  = np.zeros((W, H), dtype=np.int32)
        prev_cost = dist_map[:, 0].copy()
        y_arr     = np.arange(H, dtype=np.int32)

        for x in range(1, W):
            col_unary   = dist_map[:, x]
            padded      = np.pad(prev_cost, pad, constant_values=INF)
            windows     = np.lib.stride_tricks.sliding_window_view(padded, win)
            total       = windows + trans_kernel[np.newaxis, :]
            best_idx    = np.argmin(total, axis=1)
            backptrs[x] = np.clip(y_arr - pad + best_idx, 0, H - 1)
            prev_cost   = col_unary + total[y_arr, best_idx]

        trace_y        = np.zeros(W, dtype=np.int32)
        trace_y[W - 1] = int(np.argmin(prev_cost))
        for x in range(W - 2, -1, -1):
            trace_y[x] = backptrs[x + 1][trace_y[x + 1]]
        return trace_y


def _estimate_px_per_mm_from_dimensions(image: np.ndarray) -> float:
    H, W = image.shape[:2]
    candidates = [(297.0, 210.0), (279.4, 215.9), (280.0, 216.0), (250.0, 200.0)]
    best_w_mm, best_h_mm = min(candidates, key=lambda p: abs((W / H) - (p[0] / p[1])))
    return float(np.sqrt((W / best_w_mm) * (H / best_h_mm)))


def _extract_two_level_otsu_mask(work_image: np.ndarray, default_grid_mask: np.ndarray) -> np.ndarray:
    """Extracts dark ECG trace ink using 2-Level Otsu thresholding."""
    if work_image.ndim != 3:
        return default_grid_mask

    b_ch, g_ch, r_ch = cv2.split(work_image)
    avg_br    = (b_ch.astype(np.float32) + g_ch.astype(np.float32) + r_ch.astype(np.float32)) / 3.0
    avg_br_u8 = np.clip(avg_br, 0, 255).astype(np.uint8)

    try:
        otsu1, _ = cv2.threshold(avg_br_u8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        dark_pixels = avg_br[avg_br < float(otsu1)].flatten()
        if len(dark_pixels) < 100:
            return default_grid_mask

        dark_u8  = np.clip(dark_pixels, 0, 255).astype(np.uint8)
        otsu2, _ = cv2.threshold(dark_u8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        mask = ((avg_br < float(otsu2)) & (avg_br > 0)).astype(np.uint8) * 255
        if np.count_nonzero(mask) > 1000:
            return mask
    except Exception:
        pass

    return default_grid_mask


def digitize_ecg(image: np.ndarray) -> dict:
    def _fail(reason: str) -> dict:
        return {
            "ok": False,
            "failure_reason": reason,
            "signals":          {lead: None for lead in REQUIRED_LEADS},
            "coverage":         {lead: 0.0  for lead in REQUIRED_LEADS},
            "leads_failed":     list(REQUIRED_LEADS),
            "sampling_rate_hz": None,
            "duration_s":       None,
            "analysis_scope":   "morphology_only",
            "parameters":       {},
        }

    if image is None or image.size == 0 or not isinstance(image, np.ndarray):
        return _fail("Input image is invalid or empty")

    try:
        image_rect, was_rectified, _ = PerspectiveRectifier().rectify(image)
        work_image = image_rect if was_rectified else image

        std_img  = ImageStandardizer(ImageStandardizationConfig()).standardize(work_image)
        grid_sup = PeriodicGridSuppressor(GridDetectionConfig()).suppress(std_img.initial_ink_mask)

        try:
            px_per_mm_grid = derive_px_per_mm(grid_sup.geometry)
        except Exception:
            px_per_mm_grid = None

        px_per_mm_dim = _estimate_px_per_mm_from_dimensions(work_image)

        if px_per_mm_grid is None or abs(px_per_mm_grid - px_per_mm_dim) / max(px_per_mm_dim, 0.1) > 0.30:
            px_per_mm = px_per_mm_dim
        else:
            px_per_mm = px_per_mm_grid

        # ── Adaptive mask selection ───────────────────────────────────────────
        use_grid_mask = (
            px_per_mm_grid is not None
            and abs(px_per_mm_grid - px_per_mm_dim) / max(px_per_mm_dim, 0.1) <= 0.30
            and np.count_nonzero(grid_sup.non_grid_ink_mask) > 1000
        )
        if use_grid_mask:
            mask = grid_sup.non_grid_ink_mask
        else:
            mask = _extract_two_level_otsu_mask(work_image, grid_sup.non_grid_ink_mask)
        # ─────────────────────────────────────────────────────────────────────

    except Exception as exc:
        return _fail(f"Preprocessing failed: {exc}")

    if px_per_mm < MIN_RESOLUTION_PX_PER_MM:
        return _fail(f"Resolution {px_per_mm:.2f} px/mm is below floor {MIN_RESOLUTION_PX_PER_MM}")

    band_cfg = BandGeometryConfig()
    rois, top_y, bot_y, _, _, _, band_fail = AdaptiveBandDetector(band_cfg).detect(mask, px_per_mm)
    if band_fail:
        return _fail(f"Band detection failed: {band_fail}")

    cals = CalibrationVerifier(band_cfg).verify_all(mask, rois, px_per_mm)

    bg = BandGeometryResult(
        ok=True, failure_reason=None, band_rois=rois,
        band_heights_mm=[(b - t) / px_per_mm for t, b in rois],
        n_bands=len(rois), content_top_y=top_y, content_bottom_y=bot_y,
        calibration_pulses=cals, calibration_ok=True, px_per_mm=px_per_mm,
        resolution_ok=True, horizontal_projection=np.array([]),
        smoothed_projection=np.array([]), projection_threshold=0.0,
    )

    ext_cfg          = TraceExtractionConfig()
    crops, crop_fail = LeadCropMapper(bg, ext_cfg).map_all_leads(mask.shape[1])
    if crop_fail or crops is None:
        return _fail(f"Lead crop mapping failed: {crop_fail}")

    lead_results = ContinuousTraceExtractor(ext_cfg).extract_all_leads(mask, crops, bg)
    signals, coverage, failed = {}, {}, []

    for lead in REQUIRED_LEADS:
        res            = lead_results[lead]
        signals[lead]  = res.signal
        coverage[lead] = res.coverage
        if not res.ok:
            failed.append(lead)

    overall_ok = len(failed) == 0
    return {
        "ok":               overall_ok,
        "failure_reason":   f"{len(failed)} lead(s) failed: {failed}" if not overall_ok else None,
        "signals":          signals,
        "coverage":         coverage,
        "leads_failed":     failed,
        "sampling_rate_hz": SAMPLE_RATE_HZ if overall_ok else None,
        "duration_s":       LEAD_DURATION_S if overall_ok else None,
        "analysis_scope":   "morphology_only",
        "parameters":       {
            "px_per_mm":                px_per_mm,
            "was_perspective_rectified": was_rectified,
            "n_bands":                  len(rois),
        },
    }

