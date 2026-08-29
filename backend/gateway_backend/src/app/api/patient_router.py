"""Production‑grade patient management router for the Gateway Backend.

Provides secure HTTP endpoints for retrieving longitudinal patient demographic
and diagnostic data from the underlying database. Enforces Row-Level Security (RLS)
by proxying the authenticated user's JWT directly to the Supabase REST API.
"""

from typing import Any, Dict, List, Union

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.core.config import gateway_config
from app.core.security import get_current_user

router: APIRouter = APIRouter(tags=["patients", "doctors"])

SUPABASE_URL: str = gateway_config.supabase_url
SUPABASE_PUBLISHABLE_KEY: str = gateway_config.supabase_publishable_key


async def get_token(request: Request) -> str:
    """Extracts the raw Bearer token from the incoming HTTP Authorization header.

    Args:
        request (Request): The incoming FastAPI request.

    Returns:
        str: The extracted cryptographic token string.

    Raises:
        HTTPException: Raises 401 if the authorization header is absent or incorrectly formatted.
    """
    auth: str | None = request.headers.get("authorization")
    if not auth:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Invalid Authorization header")
    return token


@router.get("/patients/{patient_id}")
async def get_patient(
    request: Request,
    patient_id: str,
    token: str = Depends(get_token),
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Retrieves a patient's demographic profile from the primary database.

    Args:
        request (Request): The incoming request context containing the HTTP client.
        patient_id (str): The universal identifier of the target patient.
        token (str): The JWT extracted from the request, forwarded for RLS enforcement.
        user_id (str): The authenticated user identifier.

    Returns:
        Dict[str, Any]: The complete patient demographic record.

    Raises:
        HTTPException: Raises 404 if the patient is not found, or 500-level errors
            on upstream database failures.
    """
    url: str = f"{SUPABASE_URL}/rest/v1/patient_records"
    headers: Dict[str, str] = {
        "apikey": SUPABASE_PUBLISHABLE_KEY,
        "Authorization": f"Bearer {token}",
    }
    params: Dict[str, str] = {"id": f"eq.{patient_id}", "select": "*"}

    client: httpx.AsyncClient = request.app.state.http_client
    try:
        resp: httpx.Response = await client.get(url, headers=headers, params=params, timeout=10.0)
        resp.raise_for_status()
        data: Union[List[Dict[str, Any]], Dict[str, Any]] = resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail="Supabase request failed",
        )

    if isinstance(data, list):
        if not data:
            raise HTTPException(status_code=404, detail="Patient not found")
        return data[0]
    return data


@router.get("/patients/{patient_id}/scans")
async def get_patient_scans(
    request: Request,
    patient_id: str,
    token: str = Depends(get_token),
    user_id: str = Depends(get_current_user),
    limit: int = Query(100, ge=1, le=500, description="Maximum number of scans to return"),
) -> List[Dict[str, Any]]:
    """Retrieves historical diagnostic scans associated with a specific patient.

    Args:
        request (Request): The incoming request context containing the HTTP client.
        patient_id (str): The universal identifier of the patient.
        token (str): The JWT extracted from the request for RLS enforcement.
        user_id (str): The authenticated user identifier.
        limit (int): Pagination limit controlling the maximum returned records.

    Returns:
        List[Dict[str, Any]]: A chronological list of diagnostic scan records.

    Raises:
        HTTPException: Raises corresponding HTTP status errors upon upstream database failures.
    """
    url: str = f"{SUPABASE_URL}/rest/v1/scan_results"
    headers: Dict[str, str] = {
        "apikey": SUPABASE_PUBLISHABLE_KEY,
        "Authorization": f"Bearer {token}",
    }
    params: Dict[str, Union[str, int]] = {
        "patient_id": f"eq.{patient_id}",
        "select": "*",
        "order": "created_at.desc",
        "limit": limit,
    }

    client: httpx.AsyncClient = request.app.state.http_client
    try:
        resp: httpx.Response = await client.get(url, headers=headers, params=params, timeout=10.0)
        resp.raise_for_status()
        data: Any = resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail="Supabase request failed",
        )

    if isinstance(data, list):
        return data
    return []


@router.get("/doctors/{doctor_id}")
async def get_doctor(
    request: Request,
    doctor_id: str,
    token: str = Depends(get_token),
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Retrieves a clinician's professional profile from the primary database.

    Args:
        request (Request): The incoming request context containing the HTTP client.
        doctor_id (str): The universal identifier of the clinician.
        token (str): The JWT extracted from the request for RLS enforcement.
        user_id (str): The authenticated user identifier.

    Returns:
        Dict[str, Any]: The clinician's profile record.

    Raises:
        HTTPException: Raises 404 if the doctor is not found, or 500-level errors
            upon upstream database failures.
    """
    url: str = f"{SUPABASE_URL}/rest/v1/doctor_profiles"
    headers: Dict[str, str] = {
        "apikey": SUPABASE_PUBLISHABLE_KEY,
        "Authorization": f"Bearer {token}",
    }
    params: Dict[str, str] = {"id": f"eq.{doctor_id}", "select": "*"}

    client: httpx.AsyncClient = request.app.state.http_client
    try:
        resp: httpx.Response = await client.get(url, headers=headers, params=params, timeout=10.0)
        resp.raise_for_status()
        data: Union[List[Dict[str, Any]], Dict[str, Any]] = resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail="Supabase request failed",
        )

    if isinstance(data, list):
        if not data:
            raise HTTPException(status_code=404, detail="Doctor not found")
        return data[0]
    return data


from pydantic import BaseModel, Field

from pydantic import BaseModel, Field
from typing import Optional

class CareRelationshipItem(BaseModel):
    id: str
    status: str
    is_active: bool
    created_at: str
    activated_at: Optional[str] = None
    expires_at: Optional[str] = None
    doctor_full_name: Optional[str] = None
    doctor_specialization: Optional[str] = None
    doctor_current_hospital: Optional[str] = None

class RevokeCareRequest(BaseModel):
    relationship_id: str = Field(..., pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

@router.get("/care-relationships", response_model=List[CareRelationshipItem])
async def list_care_relationships(
    request: Request,
    token: str = Depends(get_token),
    user_id: str = Depends(get_current_user),
) -> List[CareRelationshipItem]:
    """List all active and pending care relationships for the caller."""
    url = f"{SUPABASE_URL}/rest/v1/rpc/list_care_relationships"
    headers = {
        "apikey": SUPABASE_PUBLISHABLE_KEY,
        "Authorization": f"Bearer {token}",
    }
    client: httpx.AsyncClient = request.app.state.http_client
    try:
        resp = await client.post(url, headers=headers, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 400:
            try:
                err_data = exc.response.json()
            except ValueError:
                err_data = {}
            if err_data.get("message") == "Not authenticated":
                raise HTTPException(status_code=401, detail="Not authenticated")
                pass
        raise HTTPException(
            status_code=exc.response.status_code,
            detail="Supabase request failed",
        )
    return [CareRelationshipItem(**item) for item in data] if isinstance(data, list) else []

@router.post("/care-relationships/revoke")
async def revoke_care_relationship(
    request: Request,
    payload: RevokeCareRequest,
    token: str = Depends(get_token),
    user_id: str = Depends(get_current_user),
) -> Dict[str, str]:
    """Revoke an active or pending care relationship."""
    url = f"{SUPABASE_URL}/rest/v1/rpc/revoke_care"
    headers = {
        "apikey": SUPABASE_PUBLISHABLE_KEY,
        "Authorization": f"Bearer {token}",
    }
    client: httpx.AsyncClient = request.app.state.http_client
    try:
        resp = await client.post(url, headers=headers, json={"p_id": payload.relationship_id}, timeout=10.0)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 400:
            try:
                err_data = exc.response.json()
            except ValueError:
                err_data = {}
            if err_data.get("message") == "no live relationship":
                raise HTTPException(status_code=404, detail="no live relationship")
            if err_data.get("message") == "Not authenticated":
                raise HTTPException(status_code=401, detail="Not authenticated")
                pass
        raise HTTPException(
            status_code=exc.response.status_code,
            detail="Supabase request failed",
        )
    return {"status": "revoked"}
