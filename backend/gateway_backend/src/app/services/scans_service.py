import uuid
from app.utils.validation_utils import parse_uuid
from typing import Optional, Any
import asyncpg

from app.models.schemas import HistoryScanItem, ExplainabilityInfo, TrendTransition, HistoryResponse, TrendResponse
from app.utils.labels import _ABNORMAL_LABELS, _NORMAL_LABELS
from app.utils.xai_utils import build_xai_authenticated_url

class ScansService:
    """Service for retrieving and analyzing historical scan data.
    
    Provides methods to fetch a user's past diagnostic scans, apply pagination,
    and compute clinical trend transitions (e.g., improving, worsening) across
    longitudinal imaging data.
    """
    @staticmethod
    def get_status(label: Optional[str], mod: str) -> str:
        """Resolve the clinical status of a label based on the definitive label set."""
        if not label:
            return "unknown"
        if label in _NORMAL_LABELS.get(mod, set()):
            return "normal"
        if label in _ABNORMAL_LABELS.get(mod, set()):
            return "abnormal"
        return "unknown"

    @staticmethod
    async def get_history(
        db_pool: asyncpg.Pool,
        user_uuid: uuid.UUID,
        modality: Optional[str],
        limit: int,
        offset: int
    ) -> HistoryResponse:
        """Fetch a paginated history of a patient's diagnostic scans.
        
        Retrieves scan records securely scoped to the provided user UUID, optionally
        filtering by imaging modality. Used to populate the patient-facing history
        dashboard.
        
        Args:
            db_pool (asyncpg.Pool): The asyncpg connection pool for database access.
            user_uuid (uuid.UUID): The authenticated patient's universal identifier.
            modality (Optional[str]): Optional filter for a specific scan modality (e.g., 'cxr').
            limit (int): Maximum number of records to return.
            offset (int): Pagination offset for retrieving subsequent pages.
            
        Returns:
            HistoryResponse: A structured response containing the total count and a list
                of scan history items.
        """
        count_query = """
            SELECT COUNT(*)
            FROM scan_results
            WHERE user_id = $1 AND modality IS NOT NULL
        """
        count_args = [user_uuid]
        if modality:
            count_query += " AND modality = $2"
            count_args.append(modality)

        data_query = """
            SELECT scan_id, modality, ai_diagnosis, confidence, scan_status, scan_date, xai_status, xai_path, storage_path
            FROM scan_results
            WHERE user_id = $1 AND modality IS NOT NULL
        """
        data_args = [user_uuid]
        if modality:
            data_query += " AND modality = $2"
            data_args.append(modality)

        # Append pagination and ordering
        data_query += f" ORDER BY scan_date DESC NULLS LAST LIMIT ${len(data_args) + 1} OFFSET ${len(data_args) + 2}"
        data_args.extend([limit, offset])

        async with db_pool.acquire() as conn:
            total_count = await conn.fetchval(count_query, *count_args)
            rows = await conn.fetch(data_query, *data_args)

        items = []
        for row in rows:
            row_xai_status = row["xai_status"] or "none"
            items.append(
                HistoryScanItem(
                    scan_id=str(row["scan_id"]),
                    modality=row["modality"],
                    ai_diagnosis=row["ai_diagnosis"] or "",
                    confidence=float(row["confidence"]) if row["confidence"] is not None else None,
                    scan_status=row["scan_status"],
                    scan_date=row["scan_date"],
                    xai_status=row_xai_status,
                    has_image=row["storage_path"] is not None,
                    explainability=ExplainabilityInfo(
                        status=row_xai_status,
                        url=build_xai_authenticated_url(row["xai_path"]),
                        modality=row["modality"],
                    ),
                )
            )

        return HistoryResponse(total_count=total_count, items=items)

    @staticmethod
    async def get_trends(
        db_pool: asyncpg.Pool,
        user_uuid: uuid.UUID,
        modality: str,
        limit: int
    ) -> TrendResponse:
        """Compute clinical progression trends across a patient's recent scans.
        
        Fetches the most recent scans for a specific modality and calculates the
        clinical trajectory between consecutive pairs. A trend transition represents
        whether a patient's condition is improving (abnormal to normal), worsening
        (normal to abnormal), unchanged, or indeterminate over time.
        
        Args:
            db_pool (asyncpg.Pool): The asyncpg connection pool for database access.
            user_uuid (uuid.UUID): The authenticated patient's universal identifier.
            modality (str): The specific imaging modality to analyze (e.g., 'cxr').
            limit (int): Maximum number of recent scans to analyze for trends.
            
        Returns:
            TrendResponse: A structured response containing the relevant scans and
                the computed clinical transitions between them.
        """
        query = """
            SELECT scan_id, modality, ai_diagnosis, confidence, scan_status, scan_date, xai_status, xai_path, storage_path
            FROM (
                SELECT scan_id, modality, ai_diagnosis, confidence, scan_status, scan_date, xai_status, xai_path, storage_path
                FROM scan_results
                WHERE user_id = $1 AND modality = $2 AND modality IS NOT NULL
                ORDER BY scan_date DESC NULLS LAST
                LIMIT $3
            ) sub
            ORDER BY scan_date ASC NULLS LAST
        """
        args = [user_uuid, modality, limit]

        async with db_pool.acquire() as conn:
            rows = await conn.fetch(query, *args)

        scans = []
        for row in rows:
            row_xai_status = row["xai_status"] or "none"
            scans.append(
                HistoryScanItem(
                    scan_id=str(row["scan_id"]),
                    modality=row["modality"],
                    ai_diagnosis=row["ai_diagnosis"] or "",
                    confidence=float(row["confidence"]) if row["confidence"] is not None else None,
                    scan_status=row["scan_status"],
                    scan_date=row["scan_date"],
                    xai_status=row_xai_status,
                    has_image=row["storage_path"] is not None,
                    explainability=ExplainabilityInfo(
                        status=row_xai_status,
                        url=build_xai_authenticated_url(row["xai_path"]),
                        modality=row["modality"],
                    ),
                )
            )

        transitions = []
        # Compute transitions between consecutive pairs
        for i in range(1, len(scans)):
            prev_scan = scans[i - 1]
            curr_scan = scans[i]

            days_between = None
            if curr_scan.scan_date and prev_scan.scan_date:
                days_between = (curr_scan.scan_date.date() - prev_scan.scan_date.date()).days

            confidence_delta = None
            if curr_scan.confidence is not None and prev_scan.confidence is not None:
                confidence_delta = round(curr_scan.confidence - prev_scan.confidence, 4)

            prev_status = ScansService.get_status(prev_scan.ai_diagnosis, modality)
            curr_status = ScansService.get_status(curr_scan.ai_diagnosis, modality)

            if prev_status == "unknown" or curr_status == "unknown":
                direction = "indeterminate"
            elif prev_status == "normal" and curr_status == "abnormal":
                direction = "worsening"
            elif prev_status == "abnormal" and curr_status == "normal":
                direction = "improving"
            elif prev_status == "abnormal" and curr_status == "abnormal":
                if prev_scan.ai_diagnosis == curr_scan.ai_diagnosis:
                    direction = "unchanged"
                else:
                    direction = "changed"
            else:  # normal -> normal
                direction = "unchanged"

            transitions.append(
                TrendTransition(
                    from_diagnosis=prev_scan.ai_diagnosis,
                    to_diagnosis=curr_scan.ai_diagnosis,
                    days_between=days_between,
                    confidence_delta=confidence_delta,
                    direction=direction,
                )
            )

        return TrendResponse(scans=scans, transitions=transitions)

    @staticmethod
    async def claim_report(
        db_pool: asyncpg.Pool,
        supabase_client: Any,
        token: str,
        caller_id: str
    ) -> "ClaimResponse":
        from fastapi import HTTPException
        from jose import jwt, JWTError, ExpiredSignatureError
        from app.core.config import gateway_config
        from app.models.schemas import ClaimResponse
        from datetime import datetime, timedelta, timezone
        import logging

        logger = logging.getLogger(__name__)

        try:
            payload = jwt.decode(token, gateway_config.report_token_secret, algorithms=["HS256"])
        except ExpiredSignatureError:
            raise HTTPException(status_code=403, detail="Token has expired. Please request a fresh QR code.")
        except JWTError:
            raise HTTPException(status_code=403, detail="Invalid token signature.")

        if payload.get("purpose") != "report_claim":
            raise HTTPException(status_code=403, detail="Invalid token purpose.")

        patient_id = payload.get("sub")
        if not patient_id:
            raise HTTPException(status_code=403, detail="Token missing subject.")

        # Always prepare the report URL to return, even if access is not granted.
        report_path = f"{patient_id}_report.pdf"
        try:
            signed_resp = await supabase_client.storage.from_("medical_reports").create_signed_url(report_path, gateway_config.signed_url_ttl_seconds)
            report_url = signed_resp.get("signedURL") or signed_resp.get("signedUrl")
            if not report_url:
                raise ValueError("Could not get signed URL.")
        except Exception as e:
            logger.error(f"Failed to sign report URL: {e}")
            raise HTTPException(status_code=500, detail="Failed to retrieve report URL.")

        if caller_id == patient_id:
            return ClaimResponse(
                report_url=report_url,
                access_granted=False,
                patient_ref=None,
                access_expires_at=None,
                reason=None
            )

        async with db_pool.acquire() as conn:
            # Check if caller is a doctor
            is_doctor = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM doctor_profiles WHERE user_id = $1)",
                parse_uuid(caller_id, 'caller_id')
            )
            if not is_doctor:
                return ClaimResponse(
                    report_url=report_url,
                    access_granted=False,
                    patient_ref=None,
                    access_expires_at=None,
                    reason=None
                )

            # Check existing care relationship
            row = await conn.fetchrow(
                "SELECT status, ended_at FROM care_relationships WHERE doctor_id = $1 AND patient_id = $2",
                parse_uuid(caller_id, 'caller_id'),
                parse_uuid(patient_id, 'patient_id')
            )

            access_granted = False
            reason = None
            expires_at = datetime.now(timezone.utc) + timedelta(days=gateway_config.care_relationship_ttl_days)

            if row:
                status = row["status"]
                ended_at = row["ended_at"]

                if ended_at is not None:
                    logger.warning(f"Care relationship for {patient_id} and {caller_id} was ended at {ended_at}. Denying QR claim.")
                    reason = "revoked"
                elif status == "active":
                    await conn.execute(
                        "UPDATE care_relationships SET expires_at = $1 WHERE doctor_id = $2 AND patient_id = $3",
                        expires_at, parse_uuid(caller_id, 'caller_id'), parse_uuid(patient_id, 'patient_id')
                    )
                    access_granted = True
                elif status == "pending":
                    await conn.execute(
                        "UPDATE care_relationships SET status = 'active', activated_at = now(), expires_at = $1 WHERE doctor_id = $2 AND patient_id = $3",
                        expires_at, parse_uuid(caller_id, 'caller_id'), parse_uuid(patient_id, 'patient_id')
                    )
                    access_granted = True
                elif status == "revoked":
                    reason = "revoked"
                elif status == "declined":
                    reason = "declined"
                else:
                    logger.warning(f"Unknown status {status} for care relationship between {patient_id} and {caller_id}.")
                    reason = "unknown_status"
            else:
                await conn.execute(
                    """
                    INSERT INTO care_relationships (patient_id, doctor_id, status, initiated_by, note, created_at, activated_at, expires_at)
                    VALUES ($1, $2, 'active', $3, 'QR claim', now(), now(), $4)
                    """,
                    parse_uuid(patient_id, 'patient_id'), parse_uuid(caller_id, 'caller_id'), parse_uuid(caller_id, 'caller_id'), expires_at
                )
                access_granted = True

            patient_ref = f"PT-{patient_id[:6].upper()}"

            if access_granted:
                return ClaimResponse(
                    report_url=report_url,
                    access_granted=True,
                    patient_ref=patient_ref,
                    access_expires_at=expires_at,
                    reason=None
                )
            else:
                return ClaimResponse(
                    report_url=report_url,
                    access_granted=False,
                    patient_ref=None,
                    access_expires_at=None,
                    reason=reason
                )

    @staticmethod
    async def get_triage(
        db_pool: asyncpg.Pool,
        caller_id: str,
        limit: int,
        offset: int
    ) -> "HistoryResponse":
        from app.models.schemas import HistoryResponse, HistoryScanItem, ExplainabilityInfo
        from app.utils.xai_utils import build_xai_authenticated_url

        async with db_pool.acquire() as conn:
            is_doctor = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM doctor_profiles WHERE user_id = $1)",
                parse_uuid(caller_id, 'caller_id')
            )
            if not is_doctor:
                from fastapi import HTTPException
                raise HTTPException(status_code=403, detail="Caller is not a registered doctor")

            query = """
                SELECT 
                    s.scan_id, s.modality, s.ai_diagnosis, s.confidence, s.scan_status, 
                    s.scan_date, s.xai_status, s.xai_path, s.storage_path, s.user_id
                FROM scan_results s
                WHERE (
                    s.doctor_id = $1::uuid
                    OR EXISTS (
                        SELECT 1 FROM care_relationships cr
                        WHERE cr.doctor_id = $1::uuid
                          AND cr.patient_id = s.user_id
                          AND cr.status = 'active'
                          AND (cr.expires_at IS NULL OR cr.expires_at > now())
                    )
                )
            """

            count_query = f"SELECT COUNT(*) FROM ({query}) AS sub"
            total_count = await conn.fetchval(count_query, parse_uuid(caller_id, 'caller_id'))

            data_query = query + " ORDER BY s.scan_status DESC, s.scan_date DESC LIMIT $2 OFFSET $3"
            rows = await conn.fetch(data_query, parse_uuid(caller_id, 'caller_id'), limit, offset)

            items = []
            for row in rows:
                row_xai_status = row["xai_status"] or "none"
                patient_uuid_str = str(row["user_id"])
                patient_ref = f"PT-{patient_uuid_str[:6].upper()}"

                items.append(
                    HistoryScanItem(
                        scan_id=str(row["scan_id"]),
                        modality=row["modality"],
                        ai_diagnosis=row["ai_diagnosis"] or "",
                        confidence=float(row["confidence"]) if row["confidence"] is not None else None,
                        scan_status=row["scan_status"],
                        scan_date=row["scan_date"],
                        xai_status=row_xai_status,
                        has_image=row["storage_path"] is not None,
                        explainability=ExplainabilityInfo(
                            status=row_xai_status,
                            url=build_xai_authenticated_url(row["xai_path"]),
                            modality=row["modality"],
                        ),
                        patient_ref=patient_ref
                    )
                )

            return HistoryResponse(total_count=total_count, items=items)
