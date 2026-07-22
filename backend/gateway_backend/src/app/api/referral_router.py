"""Proxy router for generating mock QR‑encoded patient referral payloads.

Provides endpoints to encode clinical diagnostic summaries and patient
identifiers into secure, machine-readable QR payloads for hand-off scenarios.
"""

from typing import Any, Dict

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.security import get_current_user
from app.models.schemas import ReferralRequest
from app.services.qr_service import QRGenerator




router: APIRouter = APIRouter(prefix="/referral", tags=["Referral"])


@router.post("/generate")
async def generate_referral(
    payload: ReferralRequest,
    user_id: str = Depends(get_current_user),
    qr_service: QRGenerator = Depends(),
) -> Dict[str, str]:
    """Generates a Base64-encoded mock QR payload for clinical referrals.

    Args:
        payload (ReferralRequest): The structured request containing patient data.
        user_id (str): The authenticated universal identifier of the calling user.
        qr_service (QRGenerator): The injected service managing QR generation logic.

    Returns:
        Dict[str, str]: A dictionary containing the Base64-encoded QR string.
    """
    qr_string: str = qr_service.generate_referral_qr(
        payload.patient_id,
        payload.diagnostic_summary,
    )
    return {"qr_payload": qr_string}
