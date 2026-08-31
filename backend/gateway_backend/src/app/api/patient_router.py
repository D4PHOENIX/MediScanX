"""Production‑grade patient management router for the Gateway Backend.

Provides secure HTTP endpoints for retrieving longitudinal patient demographic
and diagnostic data from the underlying database. Enforces Row-Level Security (RLS)
by proxying the authenticated user's JWT directly to the Supabase REST API.
"""

from typing import Any, Dict, List, Union, Optional
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.core.config import gateway_config
from app.core.security import get_current_user

router: APIRouter = APIRouter(tags=["patients", "doctors"])

SUPABASE_URL: str = gateway_config.supabase_url
SUPABASE_PUBLISHABLE_KEY: str = gateway_config.supabase_publishable_key

async def get_token(request: Request) -> str:
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return auth[7:]

# Care-relationship management
import logging as _logging
_care_logger = _logging.getLogger(__name__)

def _log_postgrest_error(endpoint: str, resp: "httpx.Response") -> None:
    try:
        body = resp.json()
    except Exception:
        body = resp.text
    if isinstance(body, dict):
        _care_logger.error(
            "%s PostgREST error — status=%s code=%r message=%r details=%r hint=%r",
            endpoint, resp.status_code, body.get("code"), body.get("message"),
            body.get("details"), body.get("hint"),
        )
    else:
        _care_logger.error("%s PostgREST error — status=%s body=%r", endpoint, resp.status_code, body)

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

class RevokeRequest(BaseModel):
    relationship_id: str = Field(..., pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

@router.get("/patients/care-relationships", response_model=List[CareRelationshipItem])
async def list_care_relationships(
    request: Request,
    token: str = Depends(get_token),
    user_id: str = Depends(get_current_user),
) -> list:
    url: str = f"{SUPABASE_URL}/rest/v1/rpc/list_care_relationships"
    headers: dict = {
        "apikey": SUPABASE_PUBLISHABLE_KEY,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    client: httpx.AsyncClient = request.app.state.http_client
    try:
        resp: httpx.Response = await client.post(url, headers=headers, json={}, timeout=10.0)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 400:
            try:
                err_data = exc.response.json()
            except Exception:
                err_data = {}
            if err_data.get("message") == "Not authenticated":
                raise HTTPException(status_code=401, detail="Not authenticated")
        raise HTTPException(status_code=exc.response.status_code, detail="Supabase request failed")
    except httpx.RequestError as exc:
        _care_logger.error("list_care_relationships network error: %s", exc)
        raise HTTPException(status_code=502, detail="Upstream service unavailable")

    data = resp.json()
    return [CareRelationshipItem(**item) for item in data] if isinstance(data, list) else []

@router.post("/patients/care-relationships/revoke", status_code=200)
async def revoke_care_relationship(
    request: Request,
    payload: RevokeRequest,
    token: str = Depends(get_token),
    user_id: str = Depends(get_current_user),
) -> None:
    url: str = f"{SUPABASE_URL}/rest/v1/rpc/revoke_care"
    headers: dict = {
        "apikey": SUPABASE_PUBLISHABLE_KEY,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    client: httpx.AsyncClient = request.app.state.http_client
    try:
        resp: httpx.Response = await client.post(
            url, headers=headers, json={"p_id": payload.relationship_id}, timeout=10.0
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 400:
            try:
                err_data = exc.response.json()
            except Exception:
                err_data = {}
            if err_data.get("message") == "Not authenticated":
                raise HTTPException(status_code=401, detail="Not authenticated")
            if err_data.get("message") == "no live relationship":
                raise HTTPException(status_code=404, detail="no live relationship")
        raise HTTPException(status_code=exc.response.status_code, detail="Supabase request failed")
    except httpx.RequestError as exc:
        _care_logger.error("revoke_care_relationship network error: %s", exc)
        raise HTTPException(status_code=502, detail="Upstream service unavailable")

@router.get("/patients/{patient_id}")
async def get_patient(
    request: Request,
    patient_id: str,
    token: str = Depends(get_token),
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
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
        raise HTTPException(status_code=exc.response.status_code, detail="Supabase request failed")
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
    url: str = f"{SUPABASE_URL}/rest/v1/scan_results"
    headers: Dict[str, str] = {
        "apikey": SUPABASE_PUBLISHABLE_KEY,
        "Authorization": f"Bearer {token}",
    }
    params: Dict[str, Union[str, int]] = {
        "patient_id": f"eq.{patient_id}", "select": "*", "order": "created_at.desc", "limit": limit,
    }
    client: httpx.AsyncClient = request.app.state.http_client
    try:
        resp: httpx.Response = await client.get(url, headers=headers, params=params, timeout=10.0)
        resp.raise_for_status()
        data: Any = resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail="Supabase request failed")
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
        raise HTTPException(status_code=exc.response.status_code, detail="Supabase request failed")
    if isinstance(data, list):
        if not data:
            raise HTTPException(status_code=404, detail="Doctor not found")
        return data[0]
    return data
