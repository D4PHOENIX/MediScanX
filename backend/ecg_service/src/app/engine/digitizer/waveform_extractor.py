from __future__ import annotations
from dataclasses import dataclass
import cv2
import numpy as np
from scipy import ndimage
from scipy.interpolate import PchipInterpolator

from .contracts import (
    GAIN_MM_PER_MV,
    LEAD_COLUMN_WIDTH_MM,
    PAPER_SPEED_MM_PER_S,
    REQUIRED_LEADS,
    SAMPLE_RATE_HZ,
    STANDARD_LAYOUT,
    TARGET_SAMPLES,
)
from .layout_slicer import BandGeometryResult


@dataclass
class TraceExtractionConfig:
    label_exclusion_mm: float = 7.0
    cal_pulse_margin_mm: float = 9.4
    max_gap_samples: int = 10
    gap_ink_distance_threshold_mm: float = 1.5
    max_jump_mm: float = 3.0
    continuity_weight_mm2: float = 0.05
    min_coverage: float = 0.65
    baseline_smoothing_sigma: float = 2.0
    interpolation_margin_s: float = 0.05


@dataclass
class LeadExtractionResult:
    lead_name: str
    ok: bool
    signal: np.ndarray | None
    coverage: float
    max_gap_samples_observed: int
    baseline_y_px: float | None
    failure_reason: str | None
    trace_y_px: np.ndarray | None = None


class LeadCropMapper:
    def __init__(self, band_geometry: BandGeometryResult, config: TraceExtractionConfig | None = None) -> None:
        self.bg = band_geometry
        self.cfg = config or TraceExtractionConfig()

    def map_all_leads(self, image_width: int) -> tuple[dict[str, tuple[int, int, int, int]] | None, str | None]:
        px = self.bg.px_per_mm
        cfg = self.cfg

        cal_left_xs = [cr.bbox[0] for cr in self.bg.calibration_pulses if cr.passed and cr.bbox is not None]
        if cal_left_xs:
            content_right_x = min(cal_left_xs) - round(cfg.cal_pulse_margin_mm * px)
        else:
            content_right_x = round(image_width - 25.0 * px)

        col_width_px = LEAD_COLUMN_WIDTH_MM * px
        content_width_px = 4.0 * col_width_px
        content_left_x = content_right_x - content_width_px

        if content_left_x < 0 or content_right_x > image_width:
            content_left_x = round(10.0 * px)
            content_right_x = content_left_x + content_width_px

        label_excl_px = round(cfg.label_exclusion_mm * px)
        crops = {}

        for (row_idx, col_idx), lead_name in STANDARD_LAYOUT.items():
            if row_idx >= self.bg.n_bands:
                continue
            top_y, bot_y = self.bg.band_rois[row_idx]
            col_left = int(round(content_left_x + col_idx * col_width_px))
            col_right = int(round(content_left_x + (col_idx + 1) * col_width_px))
            trace_left = max(col_left + label_excl_px, 0)
            col_right = min(col_right, image_width)

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
        px = band_geometry.px_per_mm
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

        H, W = lead_mask.shape
        max_jump_px = round(cfg.max_jump_mm * px_per_mm)
        max_gap_px = round(cfg.max_gap_samples * px_per_mm * PAPER_SPEED_MM_PER_S / SAMPLE_RATE_HZ)
        gap_ink_thresh = cfg.gap_ink_distance_threshold_mm * px_per_mm
        alpha_px = cfg.continuity_weight_mm2 / (px_per_mm ** 2)

        trace_y = self._viterbi_dp(lead_mask, max_jump_px, alpha_px)
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
        max_gap_cols = max(
            [int((labeled_gaps == g).sum()) for g in range(1, n_gaps + 1)], default=0
        )
        px_per_sample = px_per_mm * PAPER_SPEED_MM_PER_S / SAMPLE_RATE_HZ
        max_gap_samples_obs = int(round(max_gap_cols / px_per_sample))

        valid_ys = trace_y[~gap_mask]
        counts, edges = np.histogram(valid_ys, bins=max(band_h // 2, 20), range=(0, band_h))
        smoothed_counts = ndimage.gaussian_filter1d(counts.astype(float), sigma=cfg.baseline_smoothing_sigma)
        baseline_y = float(
            (edges[np.argmax(smoothed_counts)] + edges[np.argmax(smoothed_counts) + 1]) / 2.0
        )

        if max_gap_cols > max_gap_px:
            return LeadExtractionResult(
                lead_name=lead_name, ok=False, signal=None, coverage=coverage,
                max_gap_samples_observed=max_gap_samples_obs, baseline_y_px=baseline_y,
                failure_reason=f"Max gap {max_gap_cols}px > {max_gap_px}px", trace_y_px=trace_y
            )

        t_px = np.arange(W) / (px_per_mm * PAPER_SPEED_MM_PER_S)
        valid_t = t_px[~gap_mask]
        valid_mv = (baseline_y - trace_y[~gap_mask]) / (px_per_mm * GAIN_MM_PER_MV)

        t_target = np.linspace(valid_t[0], valid_t[-1], TARGET_SAMPLES)
        interp = PchipInterpolator(valid_t, valid_mv, extrapolate=False)
        sig_250 = interp(t_target)

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
        H, W = mask.shape
        INF = 1e9
        dist_map = cv2.distanceTransform(
            (mask == 0).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_5
        ).astype(np.float64)

        pad = max_jump_px
        win = 2 * pad + 1
        delta = np.arange(-pad, pad + 1, dtype=np.float64)
        trans_kernel = alpha_px * (delta ** 2)

        backptrs = np.zeros((W, H), dtype=np.int32)
        prev_cost = dist_map[:, 0].copy()
        y_arr = np.arange(H, dtype=np.int32)

        for x in range(1, W):
            col_unary = dist_map[:, x]
            padded = np.pad(prev_cost, pad, constant_values=INF)
            windows = np.lib.stride_tricks.sliding_window_view(padded, win)
            total = windows + trans_kernel[np.newaxis, :]
            best_idx = np.argmin(total, axis=1)
            backptrs[x] = np.clip(y_arr - pad + best_idx, 0, H - 1)
            prev_cost = col_unary + total[y_arr, best_idx]

        trace_y = np.zeros(W, dtype=np.int32)
        trace_y[W - 1] = int(np.argmin(prev_cost))
        for x in range(W - 2, -1, -1):
            trace_y[x] = backptrs[x + 1][trace_y[x + 1]]
        return trace_y
