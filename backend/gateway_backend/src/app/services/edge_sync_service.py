"""Edge sync service for the MediScanX Gateway.

Provides the orchestration logic for syncing edge-inferred scans, separating
database and storage concerns from HTTP routing.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

from asyncpg.pool import Pool
from supabase._async.client import AsyncClient as SupabaseAsyncClient

from app.core.config import gateway_config
from app.services.scan_persistence_service import ScanPersistenceService
from app.services.storage_service import StorageService

logger: logging.Logger = logging.getLogger(__name__)


class EdgeSyncOutcome(str, Enum):
    SYNCED = "synced"
    ALREADY_SYNCED = "already_synced"
    SCAN_ID_CONFLICT = "scan_id_conflict"
    STORAGE_UPLOAD_FAILED = "storage_upload_failed"
    WRITE_FAILED = "sync_write_failed"


@dataclass
class EdgeSyncResult:
    outcome: EdgeSyncOutcome
    scan_id: str
    storage_path: Optional[str] = None
    image_url: Optional[str] = None
    detail: Optional[str] = None


class EdgeSyncService:
    """Orchestrates edge sync persistence across database and storage."""

    @staticmethod
    async def process_sync(
        db_pool: Pool,
        supabase_client: SupabaseAsyncClient,
        scan_id: str,
        final_user_id: str,
        final_doctor_id: Optional[str],
        scan_type: int,
        scan_status: int,
        ai_diagnosis: str,
        confidence: float,
        findings: str,
        metadata_dict: Dict[str, Any],
        derived_modality: str,
        content: bytes,
        content_type: str,
    ) -> EdgeSyncResult:
        """Processes an edge sync request, returning a typed outcome."""
        #
        # Step 1 — duplicate pre-check.
        #
        async with db_pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT scan_id, storage_path, user_id FROM scan_results WHERE scan_id = $1::uuid",
                scan_id,
            )

        if existing is not None:
            if str(existing["user_id"]) != final_user_id:
                # Foreign row
                return EdgeSyncResult(
                    outcome=EdgeSyncOutcome.SCAN_ID_CONFLICT,
                    scan_id=scan_id,
                    detail="scan_id belongs to another user.",
                )

            existing_storage_path = existing["storage_path"]
            if existing_storage_path:
                # Row exists with a non-null storage_path → already fully synced.
                return EdgeSyncResult(
                    outcome=EdgeSyncOutcome.ALREADY_SYNCED,
                    scan_id=scan_id,
                    storage_path=existing_storage_path,
                )
            # Row exists with null/empty storage_path → legacy partial.
            _is_partial_row = True
        else:
            _is_partial_row = False

        #
        # Step 2 — upload, then verify.
        #
        try:
            image_url, storage_path = await StorageService.upload_scan_image(
                supabase_client=supabase_client,
                bucket=gateway_config.supabase_storage_bucket,
                user_id=final_user_id,
                scan_id=scan_id,
                file_bytes=content,
                content_type=content_type,
            )
        except RuntimeError as exc:
            logger.error(
                "Storage upload raised for edge scan_id=%s user_id=%s: %s",
                scan_id,
                final_user_id,
                exc,
            )
            return EdgeSyncResult(
                outcome=EdgeSyncOutcome.STORAGE_UPLOAD_FAILED,
                scan_id=scan_id,
                detail=str(exc),
            )

        if not storage_path:
            logger.error(
                "Storage upload returned falsy object_path for edge scan_id=%s user_id=%s",
                scan_id,
                final_user_id,
            )
            return EdgeSyncResult(
                outcome=EdgeSyncOutcome.STORAGE_UPLOAD_FAILED,
                scan_id=scan_id,
                detail="Storage returned no object path",
            )

        authenticated_image_url = image_url.replace("/object/public/", "/object/authenticated/")

        #
        # Step 3 — insert (or update partial row).
        #
        if _is_partial_row:
            try:
                async with db_pool.acquire() as conn:
                    updated = await conn.fetchrow(
                        """
                        UPDATE scan_results
                        SET storage_path = $1, image_url = $2
                        WHERE scan_id = $3::uuid AND user_id = $4::uuid AND storage_path IS NULL
                        RETURNING scan_id
                        """,
                        storage_path,
                        authenticated_image_url,
                        scan_id,
                        final_user_id,
                    )
            except Exception as exc:
                logger.error(
                    "Database update failed for partial edge row scan_id=%s user_id=%s: %s",
                    scan_id,
                    final_user_id,
                    exc,
                )
                return EdgeSyncResult(
                    outcome=EdgeSyncOutcome.WRITE_FAILED,
                    scan_id=scan_id,
                    detail=str(exc),
                )
            
            return EdgeSyncResult(
                outcome=EdgeSyncOutcome.ALREADY_SYNCED,
                scan_id=scan_id,
                storage_path=storage_path,
            )

        try:
            was_inserted: bool = await ScanPersistenceService.insert_scan_result(
                pool=db_pool,
                scan_id=scan_id,
                user_id=final_user_id,
                doctor_id=final_doctor_id,
                scan_type=scan_type,
                scan_status=scan_status,
                image_url=authenticated_image_url,
                ai_diagnosis=ai_diagnosis,
                confidence=confidence,
                findings=findings,
                metadata=metadata_dict,
                inference_source="edge",
                storage_path=storage_path,
                modality=derived_modality,
            )
        except Exception as exc:
            logger.error(
                "Database insert failed for edge scan_id=%s user_id=%s: %s",
                scan_id,
                final_user_id,
                exc,
            )
            try:
                await StorageService.delete_scan_objects(
                    supabase_client=supabase_client,
                    bucket=gateway_config.supabase_storage_bucket,
                    user_id=final_user_id,
                    object_paths=[storage_path],
                )
            except Exception as cleanup_exc:
                logger.error(
                    "Compensating delete failed after insert failure — orphaned objects: %s (cleanup error: %s)",
                    [storage_path],
                    cleanup_exc,
                )
            return EdgeSyncResult(
                outcome=EdgeSyncOutcome.WRITE_FAILED,
                scan_id=scan_id,
                detail=str(exc),
            )

        if was_inserted:
            return EdgeSyncResult(
                outcome=EdgeSyncOutcome.SYNCED,
                scan_id=scan_id,
                image_url=authenticated_image_url,
                storage_path=storage_path,
            )

        async with db_pool.acquire() as conn:
            conflicting_row = await conn.fetchrow(
                "SELECT user_id, storage_path FROM scan_results WHERE scan_id = $1::uuid",
                scan_id,
            )

        if conflicting_row and str(conflicting_row["user_id"]) != final_user_id:
            if conflicting_row["storage_path"] != storage_path:
                try:
                    await StorageService.delete_scan_objects(
                        supabase_client=supabase_client,
                        bucket=gateway_config.supabase_storage_bucket,
                        user_id=final_user_id,
                        object_paths=[storage_path],
                    )
                except Exception as cleanup_exc:
                    logger.error(
                        "Compensating delete failed for foreign conflict orphaned object: %s",
                        cleanup_exc,
                    )
            return EdgeSyncResult(
                outcome=EdgeSyncOutcome.SCAN_ID_CONFLICT,
                scan_id=scan_id,
                detail="scan_id claimed by another user during sync.",
            )

        return EdgeSyncResult(
            outcome=EdgeSyncOutcome.ALREADY_SYNCED,
            scan_id=scan_id,
            storage_path=storage_path,
        )
