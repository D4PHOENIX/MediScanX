from __future__ import annotations
from dataclasses import dataclass
import cv2
import numpy as np
from scipy import ndimage
from scipy.signal import find_peaks

from .contracts import (
    GridGeometry,
    MIN_RESOLUTION_PX_PER_MM,
)


def derive_px_per_mm(geometry: GridGeometry) -> float:
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
    aspect_ratio_tolerance: float = 0.15
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
    smoothing_sigma_mm: float = 5.0
    min_band_height_fraction: float = 0.08
    max_band_height_fraction: float = 0.45
    header_exclusion_fraction: float = 0.08
    footer_exclusion_fraction: float = 0.05
    expected_band_counts: tuple[int, ...] = (3, 4)
    min_peak_distance_fraction: float = 0.15
    peak_prominence_fraction: float = 0.25
    cal_pulse_height_mm: float = 10.0
    cal_pulse_width_mm: float = 5.0
    cal_pulse_tolerance: float = 0.20
    cal_search_width_fraction: float = 0.15
    min_resolution_px_per_mm: float = MIN_RESOLUTION_PX_PER_MM


class AdaptiveBandDetector:
    def __init__(self, config: BandGeometryConfig | None = None) -> None:
        self.config = config or BandGeometryConfig()

    def detect(self, non_grid_ink_mask: np.ndarray, px_per_mm: float):
        H, W = non_grid_ink_mask.shape[:2]
        cfg = self.config

        content_top_y = int(H * cfg.header_exclusion_fraction)
        content_bottom_y = int(H * (1.0 - cfg.footer_exclusion_fraction))
        content_mask = non_grid_ink_mask[content_top_y:content_bottom_y, :]
        content_H = content_bottom_y - content_top_y

        proj_content = (content_mask > 0).astype(np.float64).sum(axis=1) / float(W)
        sigma_px = max(cfg.smoothing_sigma_mm * px_per_mm, 8.0)
        smoothed_content = ndimage.gaussian_filter1d(proj_content, sigma=sigma_px)

        full_proj = np.zeros(H, dtype=np.float64)
        full_smoothed = np.zeros(H, dtype=np.float64)
        full_proj[content_top_y:content_bottom_y] = proj_content
        full_smoothed[content_top_y:content_bottom_y] = smoothed_content

        peak_max = float(smoothed_content.max())
        if peak_max <= 0:
            return [], content_top_y, content_bottom_y, full_proj, full_smoothed, 0.0, "Band detection failed: No ink found"

        min_peak_dist_px = int(content_H * cfg.min_peak_distance_fraction)
        min_peak_height = peak_max * 0.10
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
            left = 0 if i == 0 else (peaks[i - 1] + peak) // 2
            right = content_H if i == len(peaks) - 1 else (peak + peaks[i + 1]) // 2

            h_frac = (right - left) / float(H)
            if cfg.min_band_height_fraction <= h_frac <= cfg.max_band_height_fraction:
                band_rois.append((content_top_y + left, content_top_y + right))

        if len(band_rois) not in cfg.expected_band_counts:
            return [], content_top_y, content_bottom_y, full_proj, full_smoothed, min_peak_height, f"Band detection failed: Detected {len(band_rois)} valid bands; expected {cfg.expected_band_counts}"

        return band_rois, content_top_y, content_bottom_y, full_proj, full_smoothed, min_peak_height, None


@dataclass
class CalibrationPulseResult:
    band_index: int
    detected: bool
    height_px: float
    width_px: float
    height_mm: float
    width_mm: float
    height_error_pct: float
    width_error_pct: float
    passed: bool
    failure_reason: str | None
    bbox: tuple[int, int, int, int] | None = None


@dataclass
class BandGeometryResult:
    ok: bool
    failure_reason: str | None
    band_rois: list[tuple[int, int]]
    band_heights_mm: list[float]
    n_bands: int
    content_top_y: int
    content_bottom_y: int
    calibration_pulses: list[CalibrationPulseResult]
    calibration_ok: bool
    px_per_mm: float
    resolution_ok: bool
    horizontal_projection: np.ndarray
    smoothed_projection: np.ndarray
    projection_threshold: float


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
        cfg = self.config
        top_y, bot_y = roi
        img_W = mask.shape[1]
        tol = cfg.cal_pulse_tolerance

        search_left = int(round(img_W * (1.0 - cfg.cal_search_width_fraction)))
        band_mask = mask[top_y:bot_y, search_left:]

        def _fail(reason: str) -> CalibrationPulseResult:
            return CalibrationPulseResult(
                band_index=band_idx, detected=False, height_px=0, width_px=0,
                height_mm=0, width_mm=0, height_error_pct=0, width_error_pct=0,
                passed=False, failure_reason=reason
            )

        kernel_v = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 15))
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
                b1, b2 = bars[i], bars[j]
                sep_mm = (b2["x"] - b1["x"]) / px_per_mm
                sep_err = (sep_mm - cfg.cal_pulse_width_mm) / cfg.cal_pulse_width_mm * 100.0
                avg_h_mm = (b1["h_mm"] + b2["h_mm"]) / 2.0
                h_err = (avg_h_mm - cfg.cal_pulse_height_mm) / cfg.cal_pulse_height_mm * 100.0

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
