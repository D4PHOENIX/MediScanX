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
    final_user_id = patient_id if patient_id else user_id
    final_doctor_id = user_id if patient_id else doctor_id

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
