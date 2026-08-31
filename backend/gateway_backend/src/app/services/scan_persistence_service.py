"""Scan result persistence service for the MediScanX Gateway.

Provides an asynchronous interface to write structured scan results into the
``scan_results`` PostgreSQL table via the shared ``asyncpg`` connection pool.
This service is the **sole write path** for ``scan_results`` from the gateway —
both cloud inference and edge (TFLite) sync flows use it.
"""

import json
import logging
from typing import Any, Dict, Optional

import asyncpg

from app.utils.labels import _ABNORMAL_LABELS, _NORMAL_LABELS

logger: logging.Logger = logging.getLogger(__name__)

# Threshold boundaries for deriving scan_status from confidence scores.
# Mirrors the clinical severity tiers displayed in the Flutter UI.
_HIGH_RISK_THRESHOLD: float = 0.85
_WARNING_THRESHOLD: float = 0.50


class ScanPersistenceService:
    """Encapsulates all ``scan_results`` INSERT/UPSERT operations for the gateway.

    All methods are static — the asyncpg pool is passed in explicitly so the
    service has no hidden state and is trivially testable.
    """

    @staticmethod
    def derive_scan_status(
        confidence: float,
        ai_diagnosis: Optional[str] = None,
        modality: Optional[str] = None,
    ) -> int:
        """Maps a model confidence score and diagnosis to the ``scan_status`` integer enum.

        The thresholds align with the clinical severity tiers displayed in the
        Flutter UI and used by the LangGraph agent's risk assessment tools.

        Args:
            confidence: The top-1 prediction confidence in the range [0.0, 1.0].
            ai_diagnosis: The predicted clinical finding.
            modality: The scanning modality (e.g., 'cxr', 'ecg', 'skin').

        Returns:
            int: 2 (High Risk), 1 (Warning), or 0 (Normal).
        """
        if not ai_diagnosis or not modality:
            return 1
            
        if ai_diagnosis in _NORMAL_LABELS.get(modality, set()):
            return 0
            
        if ai_diagnosis in _ABNORMAL_LABELS.get(modality, set()):
            if confidence >= _HIGH_RISK_THRESHOLD:
                return 2  # High Risk
            if confidence >= _WARNING_THRESHOLD:
                return 1  # Warning
            return 0  # Normal
            
        return 1

    @staticmethod
    async def insert_scan_result(
        pool: asyncpg.Pool,
        scan_id: str,
        user_id: str,
        scan_type: int,
        scan_status: int,
        image_url: str,
        ai_diagnosis: str,
        confidence: float,
        inference_source: str,
        doctor_id: Optional[str] = None,
        findings: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        storage_path: Optional[str] = None,
        modality: Optional[str] = None,
        xai_path: Optional[str] = None,
        xai_status: str = 'none',
    ) -> bool:
        """Inserts a single scan result row into the ``scan_results`` table.

        The INSERT is idempotent via ``ON CONFLICT (scan_id) DO NOTHING``.
        This guarantees that duplicate submissions — such as a mobile client
        retrying a failed sync — never produce duplicate rows.

        Args:
            pool: The shared ``asyncpg`` connection pool from ``app.state``.
            scan_id: The scan's UUID.  For cloud scans this is server-generated;
                for edge scans this is the client-generated UUID from the outbox.
            user_id: The authenticated patient's UUID (from the Supabase JWT ``sub`` claim).
            scan_type: Modality integer — ``0`` ECG, ``1`` X-Ray, ``2`` Skin Lesion.
            scan_status: Severity integer — ``0`` Normal, ``1`` Warning, ``2`` High Risk.
            image_url: The public Supabase Storage URL of the uploaded scan image.
            ai_diagnosis: The top-1 predicted class label from the ML engine.
            confidence: The top-1 prediction confidence score in [0.0, 1.0].
            inference_source: Either ``"cloud"`` or ``"edge"``.
            doctor_id: The doctor's UUID if captured during the session; optional.
            findings: Free-text diagnostic findings from the ML engine; optional.
            metadata: The full JSON payload from the ML engine, stored verbatim
                in the ``metadata`` JSONB column for auditability; optional.
            storage_path: The deterministic object path within Supabase Storage; optional.

        Returns:
            bool: ``True`` if the row was inserted, ``False`` if it already existed
                (idempotent conflict — not an error).

        Raises:
            asyncpg.PostgresError: On any hard database error (connection failure,
                constraint violation other than the PK conflict, etc.).
        """
        metadata_json: str = json.dumps(metadata or {})

        query = """
            INSERT INTO scan_results (
                scan_id,
                user_id,
                doctor_id,
                scan_type,
                scan_status,
                image_url,
                ai_diagnosis,
                findings,
                confidence,
                metadata,
                inference_source,
                storage_path,
                modality,
                scan_date,
                xai_path,
                xai_status
            ) VALUES (
                $1::uuid,
                $2::uuid,
                $3::uuid,
                $4,
                $5,
                $6,
                $7,
                $8,
                $9,
                $10::jsonb,
                $11,
                $12,
                $13,
                timezone('utc'::text, now()),
                $14,
                $15
            )
            ON CONFLICT (scan_id) DO NOTHING
        """

        async with pool.acquire() as conn:
            result = await conn.execute(
                query,
                scan_id,
                user_id,
                doctor_id,   # asyncpg treats None as SQL NULL automatically
                scan_type,
                scan_status,
                image_url,
                ai_diagnosis,
                findings,
                confidence,
                metadata_json,
                inference_source,
                storage_path,
                modality,
                xai_path,
                xai_status,
            )

        # asyncpg returns a string like "INSERT 0 1" or "INSERT 0 0"
        was_inserted: bool = result.endswith(" 1")
        if was_inserted:
            logger.info(
                "scan_results INSERT: scan_id=%s source=%s type=%d status=%d",
                scan_id,
                inference_source,
                scan_type,
                scan_status,
            )
        else:
            logger.info(
                "scan_results conflict (already exists): scan_id=%s", scan_id
            )
        return was_inserted
