"""Validation utilities for the Gateway backend."""

import uuid as uuid_mod
from fastapi import HTTPException, status

def _validate_uuid(value: str, field_name: str) -> str:
    """Validates that a string is a well-formed UUID.

    Args:
        value: The string to validate.
        field_name: Human-readable field name for the error message.

    Returns:
        str: The input value (unchanged) if valid.

    Raises:
        HTTPException: 422 Unprocessable Entity if the value is not a valid UUID.
    """
    try:
        uuid_mod.UUID(value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"'{field_name}' must be a valid UUID. Received: '{value}'",
        )
    return value
