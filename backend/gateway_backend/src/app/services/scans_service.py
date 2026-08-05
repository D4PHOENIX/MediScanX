import uuid
from typing import Optional
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
