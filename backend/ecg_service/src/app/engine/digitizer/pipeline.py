from __future__ import annotations
import cv2
import numpy as np

from .contracts import (
    GridDetectionConfig,
    ImageStandardizationConfig,
    LEAD_DURATION_S,
    MIN_RESOLUTION_PX_PER_MM,
    REQUIRED_LEADS,
    SAMPLE_RATE_HZ,
)
from .grid_suppression import ImageStandardizer, PeriodicGridSuppressor
from .layout_slicer import (
    AdaptiveBandDetector,
    BandGeometryConfig,
    BandGeometryResult,
    CalibrationVerifier,
    PerspectiveRectifier,
    derive_px_per_mm,
)
from .waveform_extractor import (
    ContinuousTraceExtractor,
    LeadCropMapper,
    TraceExtractionConfig,
)


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
    avg_br = (b_ch.astype(np.float32) + g_ch.astype(np.float32) + r_ch.astype(np.float32)) / 3.0
    avg_br_u8 = np.clip(avg_br, 0, 255).astype(np.uint8)

    try:
        otsu1, _ = cv2.threshold(avg_br_u8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        dark_pixels = avg_br[avg_br < float(otsu1)].flatten()
        if len(dark_pixels) < 100:
            return default_grid_mask

        dark_u8 = np.clip(dark_pixels, 0, 255).astype(np.uint8)
        otsu2, _ = cv2.threshold(dark_u8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        mask = ((avg_br < float(otsu2)) & (avg_br > 0)).astype(np.uint8) * 255
        if np.count_nonzero(mask) > 1000:
            return mask
    except Exception:
        pass

    return default_grid_mask


def digitize_ecg(image: np.ndarray) -> dict:
    """Reconstruct 12-lead ECG signals from an input paper image."""

    def _fail(reason: str) -> dict:
        return {
            "ok": False,
            "failure_reason": reason,
            "signals": {lead: None for lead in REQUIRED_LEADS},
            "coverage": {lead: 0.0 for lead in REQUIRED_LEADS},
            "leads_failed": list(REQUIRED_LEADS),
            "sampling_rate_hz": None,
            "duration_s": None,
            "analysis_scope": "morphology_only",
            "parameters": {},
        }

    if image is None or image.size == 0 or not isinstance(image, np.ndarray):
        return _fail("Input image is invalid or empty")

    try:
        image_rect, was_rectified, _ = PerspectiveRectifier().rectify(image)
        work_image = image_rect if was_rectified else image

        std_img = ImageStandardizer(ImageStandardizationConfig()).standardize(work_image)
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

    ext_cfg = TraceExtractionConfig()
    crops, crop_fail = LeadCropMapper(bg, ext_cfg).map_all_leads(mask.shape[1])
    if crop_fail or crops is None:
        return _fail(f"Lead crop mapping failed: {crop_fail}")

    lead_results = ContinuousTraceExtractor(ext_cfg).extract_all_leads(mask, crops, bg)
    signals, coverage, failed = {}, {}, []

    for lead in REQUIRED_LEADS:
        res = lead_results[lead]
        signals[lead] = res.signal
        coverage[lead] = res.coverage
        if not res.ok:
            failed.append(lead)

    overall_ok = len(failed) == 0
    return {
        "ok": overall_ok,
        "failure_reason": f"{len(failed)} lead(s) failed: {failed}" if not overall_ok else None,
        "signals": signals,
        "coverage": coverage,
        "leads_failed": failed,
        "sampling_rate_hz": SAMPLE_RATE_HZ if overall_ok else None,
        "duration_s": LEAD_DURATION_S if overall_ok else None,
        "analysis_scope": "morphology_only",
        "parameters": {
            "px_per_mm": px_per_mm,
            "was_perspective_rectified": was_rectified,
            "n_bands": len(rois),
        },
    }
