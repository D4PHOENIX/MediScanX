"""
Router module handling automated, asynchronous event triggers from Supabase.
"""

from fastapi import APIRouter, status
from app.models.schemas import ScanResultPayload
import logging

# Initialize module-level logger
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Infrastructure Events"])

@router.post(
    "/scan-inserted",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=dict,
    summary="Process new edge synchronization",
    description="Consumes a webhook triggered by a new database insertion and queues it for AI orchestration."
)
async def process_new_scan(payload: ScanResultPayload) -> dict:
    """
    Webhook target for Supabase 'INSERT' triggers on the scan_results table.

    This function leverages the ScanResultPayload Pydantic model to automatically
    parse, validate and type cast the incoming JSON string.
    
    Args:
        payload (ScanResultPayload): The strictly validated diagnostic data.

    Returns:
        dict: A structured acknowledgement dictionary required by the Supabase webhook engine.
        
    Raises:
        HTTPException: Automatically raised by the FastAPI with a 422 Unprocessable Entity
                        if the incoming data violates the Pydantic schema.
    """
    logger.info(f"Recieved new synchronization payload: {repr(payload)}")
    
    # RAG integration will be invoked here... 
    
    return {
        "status": "acknowledged",
        "message": f"Scan {payload.scan_id} received securely.",
        "risk_level": payload.scan_status.name
    }