from __future__ import annotations
import cv2
import numpy as np
import numpy.typing as npt
from scipy.signal import correlate, find_peaks

from .contracts import (
    DigitizationFailure,
    GridDetectionConfig,
    GridGeometry,
    GridSuppressionResult,
    ImageStandardizationConfig,
    StandardizedECGImage,
)


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
