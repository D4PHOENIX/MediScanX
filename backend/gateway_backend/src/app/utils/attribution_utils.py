"""Attribution utilities for the Gateway backend ML routers."""

import uuid as uuid_mod
import logging

logger = logging.getLogger(__name__)

def resolve_attribution(
    user_id: str,
    patient_id: str | None,
    doctor_id: str | None,
    service_name: str
) -> tuple[str, str | None, bool]:
    """Resolves final patient and doctor IDs and verifies UUID validity for persistence.

    Args:
        user_id: The authenticated user's ID.
        patient_id: Optional patient ID provided in the request.
        doctor_id: Optional doctor ID provided in the request.
        service_name: Name of the service (for logging).

    Returns:
        Tuple containing final_user_id (the patient), final_doctor_id, and a boolean indicating
        if final_user_id is a valid UUID (required for persistence).
    """
    from fastapi import HTTPException, status
    
    # Gate doctor attribution: because there is currently no role verification
    # or doctor-patient relationship model, we strictly prevent any caller from
    # attributing a scan to a different user.
    if patient_id and patient_id != user_id:
        logger.warning(
            "[%s] Doctor attribution blocked: user_id=%s attempted to attribute scan to patient_id=%s. "
            "Doctor attribution is currently disabled until RBAC is implemented.",
            service_name,
            user_id,
            patient_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Doctor attribution is currently disabled. You may only upload scans for your own account.",
        )

    final_user_id = user_id
    final_doctor_id = doctor_id

    is_valid_uuid = True
    try:
        uuid_mod.UUID(final_user_id)
    except ValueError:
        is_valid_uuid = False
        logger.warning(
            "%s persistence skipped: user_id '%s' is not a valid UUID. "
            "This is expected in DEV_MODE (dev-token). "
            "Use a real Supabase JWT to test persistence.",
            service_name,
            final_user_id,
        )

    return final_user_id, final_doctor_id, is_valid_uuid
