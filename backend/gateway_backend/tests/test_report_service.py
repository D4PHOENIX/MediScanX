import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.main import app
from app.services.report_service import ReportGenerator
import app.api.report_router as report_router
from fastapi.testclient import TestClient
import datetime
import uuid

client = TestClient(app)

@pytest.fixture(autouse=True)
def mock_config():
    with patch("app.api.report_router.gateway_config") as mock_config:
        mock_config.database_url = "postgresql://mock"
        yield mock_config

# Test 5: Verify GenerateReportRequest schema does not contain llm_summary
def test_generate_report_request_schema():
    from app.models.schemas import GenerateReportRequest
    schema = GenerateReportRequest.schema()
    assert "llm_summary" not in schema["properties"], "llm_summary should be removed from GenerateReportRequest"


@pytest.mark.asyncio
async def test_generate_report_own_scans_succeeds(auth_headers):
    # Mock supabase (service-role client for storage)
    mock_supabase_client = MagicMock()
    mock_bucket = AsyncMock()
    mock_supabase_client.storage.from_.return_value = mock_bucket
    mock_bucket.create_signed_url.return_value = {"signedURL": "https://signed.mock/report.pdf"}
    mock_bucket.download.return_value = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\xdacd\xf8\xcfP\x0f\x00\x03\x86\x01\x80Z4}k\x00\x00\x00\x00IEND\xaeB`\x82'
    app.state.supabase_client = mock_supabase_client

    # Mock asyncpg (for fetch_scan_metadata which still uses asyncpg)
    mock_conn = AsyncMock()
    # Return realistic scan_results rows
    mock_conn.fetch.return_value = [
        {
            "scan_id": uuid.uuid4(),
            "modality": "CXR",
            "ai_diagnosis": "Pneumonia",
            "confidence": 0.95,
            "scan_date": datetime.datetime.now(datetime.timezone.utc),
            "xai_status": "generated",
            "xai_path": "path/to/xai",
            "storage_path": None
        }
    ]
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\xdacd\xf8\xcfP\x0f\x00\x03\x86\x01\x80Z4}k\x00\x00\x00\x00IEND\xaeB`\x82'

    # Mock user-scoped client for the INSERT into public.reports
    mock_user_client = MagicMock()
    mock_insert_result = MagicMock()
    mock_insert_result.data = [{"report_id": str(uuid.uuid4())}]
    mock_user_client.table.return_value.insert.return_value.execute = AsyncMock(return_value=mock_insert_result)

    with patch("asyncpg.connect", return_value=mock_conn), \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response), \
         patch("app.api.report_router.make_user_client", new_callable=AsyncMock, return_value=mock_user_client):
        response = client.post(
            "/api/v1/reports/generate",
            json={
                "selected_scan_ids": [str(uuid.uuid4())],
                "patient_id": "test-dev-user"
            },
            headers={"Authorization": "Bearer test-dev-token-secret"}
        )
        assert response.status_code == 200
        assert response.json()["message"] == "Report generated"



@pytest.mark.asyncio
async def test_generate_report_unauthorized_is_rejected(auth_headers):
    mock_supabase_client = MagicMock()
    app.state.supabase_client = mock_supabase_client

    mock_conn = AsyncMock()
    # Return empty list, signifying no matching scans found OR access denied
    mock_conn.fetch.return_value = []
    
    with patch("asyncpg.connect", return_value=mock_conn):
        response = client.post(
            "/api/v1/reports/generate",
            json={
                "selected_scan_ids": [str(uuid.uuid4())],
                "patient_id": "other-user-id"
            },
            headers={"Authorization": "Bearer test-dev-token-secret"}
        )
        assert response.status_code == 403
        assert "access denied" in response.json()["detail"].lower()
        
        # Assert the query string includes the ownership check
        called_query = mock_conn.fetch.call_args[0][0]
        assert "care_relationships" in called_query
        assert "doctor_id = $2::uuid" in called_query
        assert "status = 'active'" in called_query


@pytest.mark.asyncio
async def test_download_endpoint_own_report_succeeds(auth_headers):
    """Caller's own report: RLS returns a row, storage returns a signed URL, 307 redirect."""
    report_id = str(uuid.uuid4())
    storage_path = f"test-dev-user/{report_id}.pdf"

    mock_supabase_client = MagicMock()
    mock_bucket = AsyncMock()
    mock_supabase_client.storage.from_.return_value = mock_bucket
    mock_bucket.create_signed_url.return_value = {"signedURL": "https://signed.mock/report.pdf"}
    app.state.supabase_client = mock_supabase_client

    # Mock the request-scoped user client: RLS returns one row with the storage_path.
    mock_user_client = MagicMock()
    mock_fetch_result = MagicMock()
    mock_fetch_result.data = [{"storage_path": storage_path}]
    mock_user_client.table.return_value.select.return_value.eq.return_value.execute = AsyncMock(
        return_value=mock_fetch_result
    )

    with patch("app.api.report_router.make_user_client", new_callable=AsyncMock, return_value=mock_user_client):
        response = client.get(
            f"/api/v1/reports/download/{report_id}",
            headers={"Authorization": "Bearer test-dev-token-secret"},
            follow_redirects=False
        )
        assert response.status_code == 307
        assert response.headers["location"] == "https://signed.mock/report.pdf"
        # The path passed to storage must come from the DB row, not a template.
        mock_bucket.create_signed_url.assert_awaited_once_with(storage_path, 86400)


@pytest.mark.asyncio
async def test_download_endpoint_unauthorized_is_rejected(auth_headers):
    """RLS returns no row for an unauthorized caller → 404 (enumeration-safe)."""
    report_id = str(uuid.uuid4())

    mock_supabase_client = MagicMock()
    mock_bucket = AsyncMock()
    mock_supabase_client.storage.from_.return_value = mock_bucket
    app.state.supabase_client = mock_supabase_client

    # Mock the request-scoped user client: RLS returns empty (access denied).
    mock_user_client = MagicMock()
    mock_fetch_result = MagicMock()
    mock_fetch_result.data = []
    mock_user_client.table.return_value.select.return_value.eq.return_value.execute = AsyncMock(
        return_value=mock_fetch_result
    )

    with patch("app.api.report_router.make_user_client", new_callable=AsyncMock, return_value=mock_user_client):
        response = client.get(
            f"/api/v1/reports/download/{report_id}",
            headers={"Authorization": "Bearer test-dev-token-secret"},
            follow_redirects=False
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

        # Assert create_signed_url was never called
        mock_bucket.create_signed_url.assert_not_called()


@pytest.mark.asyncio
async def test_download_endpoint_expired_care_relationship_rejected(auth_headers):
    """RLS enforces expiry: an expired care relationship → RLS returns nothing → 404."""
    # With the new endpoint, RLS enforces access, so an expired care relationship
    # simply causes the reports_doctor_select policy to return no rows.  The
    # handler sees an empty result and raises 404, the same as any other denied
    # access (enumeration-safe, consistent with the list and delete endpoints).
    report_id = str(uuid.uuid4())

    mock_supabase_client = MagicMock()
    mock_bucket = AsyncMock()
    mock_supabase_client.storage.from_.return_value = mock_bucket
    app.state.supabase_client = mock_supabase_client

    mock_user_client = MagicMock()
    mock_fetch_result = MagicMock()
    mock_fetch_result.data = []  # RLS blocked — expired relationship
    mock_user_client.table.return_value.select.return_value.eq.return_value.execute = AsyncMock(
        return_value=mock_fetch_result
    )

    with patch("app.api.report_router.make_user_client", new_callable=AsyncMock, return_value=mock_user_client):
        response = client.get(
            f"/api/v1/reports/download/{report_id}",
            headers={"Authorization": "Bearer test-dev-token-secret"},
            follow_redirects=False
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_download_endpoint_null_expiry_granted(auth_headers):
    """A doctor with a NULL-expiry active care relationship can download via RLS."""
    report_id = str(uuid.uuid4())
    storage_path = f"some-patient/{report_id}.pdf"

    mock_supabase_client = MagicMock()
    mock_bucket = AsyncMock()
    mock_supabase_client.storage.from_.return_value = mock_bucket
    mock_bucket.create_signed_url.return_value = {"signedURL": "https://signed.mock/report.pdf"}
    app.state.supabase_client = mock_supabase_client

    # RLS allows the doctor (null-expiry active care) → returns the row.
    mock_user_client = MagicMock()
    mock_fetch_result = MagicMock()
    mock_fetch_result.data = [{"storage_path": storage_path}]
    mock_user_client.table.return_value.select.return_value.eq.return_value.execute = AsyncMock(
        return_value=mock_fetch_result
    )

    with patch("app.api.report_router.make_user_client", new_callable=AsyncMock, return_value=mock_user_client):
        response = client.get(
            f"/api/v1/reports/download/{report_id}",
            headers={"Authorization": "Bearer test-dev-token-secret"},
            follow_redirects=False
        )
        assert response.status_code == 307
        assert response.headers["location"] == "https://signed.mock/report.pdf"


def _extract_story_text(story: list) -> str:
    """Extract visible text from generated PDF flowable tree."""
    texts = []
    def walk(flowable):
        if hasattr(flowable, "text") and isinstance(flowable.text, str):
            texts.append(flowable.text)
        elif hasattr(flowable, "_cellvalues"):
            for row in flowable._cellvalues:
                for cell in row:
                    if isinstance(cell, list):
                        for item in cell:
                            walk(item)
                    else:
                        walk(cell)
    for flowable in story:
        walk(flowable)
    return " ".join(texts)


@patch("app.services.report_layout.SimpleDocTemplate")
def test_pdf_story_contains_xai_status_text(mock_doc_class):
    mock_doc = MagicMock()
    mock_doc_class.return_value = mock_doc
    captured_story = []
    def capture_build(story, *args, **kwargs):
        captured_story.clear()
        captured_story.extend(story)
    mock_doc.build.side_effect = capture_build

    gen = ReportGenerator()
    patient_id = "patient-123"
    
    # Test xai_status='none'
    scan_metadata_none = [{
        "id": "scan-1",
        "modality": "ECG",
        "ai_diagnosis": "Normal",
        "confidence": 0.99,
        "timestamp": "2026-07-22T00:00:00Z",
        "xai_status": "none"
    }]
    gen._build_pdf_story(patient_id, scan_metadata_none, {}, {})
    text_none = _extract_story_text(captured_story)
    assert "No attention map available for this scan" in text_none
    
    # Test xai_status='generated'
    scan_metadata_gen = [{
        "id": "scan-2",
        "modality": "CXR",
        "ai_diagnosis": "Pneumonia",
        "confidence": 0.95,
        "timestamp": "2026-07-22T00:00:00Z",
        "xai_status": "generated",
        "xai_path": "path/to/xai"
    }]
    # With missing bytes (simulating failure to load)
    gen._build_pdf_story(patient_id, scan_metadata_gen, {}, {})
    text_gen = _extract_story_text(captured_story)
    assert "Attention map could not be retrieved" in text_gen


@pytest.mark.asyncio
async def test_generate_report_partial_scans_rejected(auth_headers):
    mock_supabase_client = MagicMock()
    app.state.supabase_client = mock_supabase_client

    mock_conn = AsyncMock()
    # 2 scans requested, but fetch only returns 1 (simulating ownership failure on one)
    mock_conn.fetch.return_value = [
        {
            "scan_id": uuid.uuid4(),
            "modality": "CXR",
            "ai_diagnosis": "Pneumonia",
            "confidence": 0.95,
            "scan_date": datetime.datetime.now(datetime.timezone.utc),
            "xai_status": "none",
            "xai_path": None,
            "storage_path": None
        }
    ]
    
    with patch("asyncpg.connect", return_value=mock_conn):
        response = client.post(
            "/api/v1/reports/generate",
            json={
                "selected_scan_ids": [str(uuid.uuid4()), str(uuid.uuid4())],
                "patient_id": "test-dev-user"
            },
            headers={"Authorization": "Bearer test-dev-token-secret"}
        )
        assert response.status_code == 403
        assert "access denied to one or more requested scans" in response.json()["detail"].lower()
        mock_supabase_client.storage.from_.assert_not_called()




# ---------------------------------------------------------------------------
# Test 15: PDF Story contains AI Summary when present
# ---------------------------------------------------------------------------

@patch("app.services.report_layout.SimpleDocTemplate")
def test_pdf_story_contains_ai_summary(mock_doc_class):
    mock_doc = MagicMock()
    mock_doc_class.return_value = mock_doc
    captured_story = []
    def capture_build(story, *args, **kwargs):
        captured_story.clear()
        captured_story.extend(story)
    mock_doc.build.side_effect = capture_build

    gen = ReportGenerator()
    patient_id = "patient-123"
    scan_metadata = [{
        "id": "scan-1",
        "modality": "CXR",
        "ai_diagnosis": "Pneumonia",
        "confidence": 0.95,
        "timestamp": "2026-07-22T00:00:00Z",
        "xai_status": "none"
    }]
    
    gen._build_pdf_story(patient_id, scan_metadata, {}, {}, ai_summary="Test AI summary text")
    
    text = _extract_story_text(captured_story)
    assert "IMPRESSION" in text
    assert "Test AI summary text" in text
    assert "This summary is AI-generated and may be incomplete or inaccurate. It is not a diagnosis. Discuss these results with a qualified clinician." in text

@pytest.mark.asyncio
async def test_generate_report_passes_custom_timeout():
    mock_supabase_client = MagicMock()
    mock_bucket = AsyncMock()
    mock_supabase_client.storage.from_.return_value = mock_bucket
    mock_bucket.create_signed_url.return_value = {"signedURL": "https://signed.mock/report.pdf"}
    
    scan_metadata = [{
        "id": "scan-1",
        "modality": "CXR",
        "ai_diagnosis": "Pneumonia",
        "confidence": 0.95,
        "timestamp": "2026-07-22T00:00:00Z",
        "xai_status": "none",
        "storage_path": None
    }]
    
    with patch("app.services.report_service.generate_hedged_text", new_callable=AsyncMock) as mock_llm, \
         patch("app.services.report_service.ReportGenerator.fetch_patient_header", new_callable=AsyncMock) as mock_header, \
         patch("app.services.report_service.ReportGenerator._build_pdf_story", return_value=b"test"):
         
        gen = ReportGenerator()
        await gen.generate_qr_report("patient-123", scan_metadata, supabase_client=mock_supabase_client)
        
        mock_llm.assert_awaited_once()
        _, kwargs = mock_llm.call_args
        assert kwargs.get("timeout") == 25.0


@patch("app.services.report_layout.SimpleDocTemplate")
def test_pdf_story_omits_ai_summary_when_none(mock_doc_class):
    mock_doc = MagicMock()
    mock_doc_class.return_value = mock_doc
    captured_story = []
    def capture_build(story, *args, **kwargs):
        captured_story.clear()
        captured_story.extend(story)
    mock_doc.build.side_effect = capture_build

    gen = ReportGenerator()
    patient_id = "patient-123"
    scan_metadata = [{
        "id": "scan-1",
        "modality": "CXR",
        "ai_diagnosis": "Pneumonia",
        "confidence": 0.95,
        "timestamp": "2026-07-22T00:00:00Z",
        "xai_status": "none"
    }]
    
    gen._build_pdf_story(patient_id, scan_metadata, {}, {}, ai_summary=None)
    
    text = _extract_story_text(captured_story)
    assert "IMPRESSION" not in text
    assert "This summary is AI-generated and may be incomplete or inaccurate" not in text


@patch("app.services.report_layout.SimpleDocTemplate")
def test_pdf_story_contains_watermark(mock_doc_class):
    mock_doc = MagicMock()
    mock_doc.page = 1
    mock_doc_class.return_value = mock_doc
    
    # When build is called, we want to extract the onFirstPage handler and call it with a mock canvas
    def capture_build(*args, **kwargs):
        handler = kwargs.get("onFirstPage")
        if handler:
            mock_canvas = MagicMock()
            handler(mock_canvas, mock_doc)
            
            # Verify watermark was drawn
            mock_canvas.drawCentredString.assert_any_call(0, 0, "MediScanX")
            # Verify transparency was set
            mock_canvas.setFillAlpha.assert_called_with(0.045)
            # Verify rotation
            mock_canvas.rotate.assert_called_with(45)

    mock_doc.build.side_effect = capture_build

    gen = ReportGenerator()
    gen._build_pdf_story("patient-123", [], {}, {})
    assert mock_doc.build.called


def test_pdf_bytes_start_with_pdf():
    gen = ReportGenerator()
    pdf_bytes = gen._build_pdf_story("patient-123", [], {}, {})
    assert pdf_bytes.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_generate_report_compensating_delete(auth_headers):
    mock_supabase_client = MagicMock()
    mock_bucket = AsyncMock()
    mock_supabase_client.storage.from_.return_value = mock_bucket
    mock_bucket.create_signed_url.return_value = {"signedURL": "https://signed.mock/report.pdf"}
    mock_bucket.download.return_value = b"test"
    app.state.supabase_client = mock_supabase_client

    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = [{"scan_id": uuid.uuid4(), "modality": "CXR", "ai_diagnosis": "Pneumonia", "confidence": 0.95, "scan_date": datetime.datetime.now(datetime.timezone.utc), "xai_status": "none", "xai_path": None, "storage_path": None}]
    
    # Make execute fail to trigger compensating delete
    mock_conn.execute.side_effect = Exception("DB error")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"test"

    with patch("asyncpg.connect", return_value=mock_conn), patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
        response = client.post(
            "/api/v1/reports/generate",
            json={"selected_scan_ids": [str(uuid.uuid4())], "patient_id": "test-dev-user"},
            headers={"Authorization": "Bearer test-dev-token-secret"}
        )
        assert response.status_code == 500
        # Assert compensating delete was called
        mock_bucket.remove.assert_called_once()
        uploaded_path = mock_bucket.remove.call_args[0][0][0]
        assert "/" in uploaded_path  # verifying folder-based path


@pytest.mark.asyncio
async def test_generate_report_two_distinct_objects(auth_headers):
    # Verify the two generated reports for the same patient have different paths (no overwrite)
    mock_supabase_client = MagicMock()
    mock_bucket = AsyncMock()
    mock_supabase_client.storage.from_.return_value = mock_bucket
    mock_bucket.create_signed_url.return_value = {"signedURL": "https://signed.mock/report.pdf"}
    app.state.supabase_client = mock_supabase_client

    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = [{"scan_id": uuid.uuid4(), "modality": "CXR", "ai_diagnosis": "Pneumonia", "confidence": 0.95, "scan_date": datetime.datetime.now(datetime.timezone.utc), "xai_status": "none", "xai_path": None, "storage_path": None}]

    # Mock user-scoped client for the INSERT into public.reports
    mock_user_client = MagicMock()
    mock_insert_result = MagicMock()
    mock_insert_result.data = [{"report_id": str(uuid.uuid4())}]
    mock_user_client.table.return_value.insert.return_value.execute = AsyncMock(return_value=mock_insert_result)

    with patch("asyncpg.connect", return_value=mock_conn), \
         patch("app.api.report_router.make_user_client", new_callable=AsyncMock, return_value=mock_user_client):
        response1 = client.post("/api/v1/reports/generate", json={"selected_scan_ids": [str(uuid.uuid4())], "patient_id": "test-dev-user"}, headers={"Authorization": "Bearer test-dev-token-secret"})
        response2 = client.post("/api/v1/reports/generate", json={"selected_scan_ids": [str(uuid.uuid4())], "patient_id": "test-dev-user"}, headers={"Authorization": "Bearer test-dev-token-secret"})
        
        assert response1.status_code == 200
        assert response2.status_code == 200
        
        calls = mock_bucket.upload.call_args_list
        assert len(calls) == 2
        path1 = calls[0][1]["path"]
        path2 = calls[1][1]["path"]
        assert path1 != path2
        assert "x-upsert" not in calls[0][1].get("file_options", {})



@pytest.mark.asyncio
async def test_get_reports_history(auth_headers):
    mock_supabase_client = MagicMock()
    mock_bucket = AsyncMock()
    mock_supabase_client.storage.from_.return_value = mock_bucket
    mock_bucket.create_signed_url.return_value = {"signedURL": "https://signed.mock/report.pdf"}
    app.state.supabase_client = mock_supabase_client

    report_id1, report_id2 = str(uuid.uuid4()), str(uuid.uuid4())

    # Build mock user-scoped SDK client simulating what PostgREST+RLS would return.
    # count query returns APIResponse with count=2
    mock_count_result = MagicMock()
    mock_count_result.count = 2
    mock_count_result.data = []
    # data query returns APIResponse with 2 rows
    mock_data_result = MagicMock()
    mock_data_result.data = [
        {"report_id": report_id1, "user_id": "test-dev-user", "created_at": datetime.datetime.now().isoformat(), "scan_ids": [str(uuid.uuid4()), str(uuid.uuid4())], "storage_path": "path1"},
        {"report_id": report_id2, "user_id": "other-user-uuid", "created_at": datetime.datetime.now().isoformat(), "scan_ids": [str(uuid.uuid4())], "storage_path": "path2"},
    ]

    mock_user_client = MagicMock()
    # Chain for count: .table("reports").select("report_id", count="exact").execute()
    mock_user_client.table.return_value.select.return_value.execute = AsyncMock(return_value=mock_count_result)
    # Chain for data: .table("reports").select(...).order(...).range(...).execute()
    mock_user_client.table.return_value.select.return_value.order.return_value.range.return_value.execute = AsyncMock(return_value=mock_data_result)

    from app.core.security import get_current_user
    app.dependency_overrides[get_current_user] = lambda: "test-dev-user"

    with patch("app.api.report_router.make_user_client", new_callable=AsyncMock, return_value=mock_user_client):
        response = client.get("/api/v1/reports", headers={"Authorization": "Bearer test-dev-token-secret"})
        app.dependency_overrides.clear()
        assert response.status_code == 200
        data = response.json()
        assert data["total_count"] == 2
        assert len(data["items"]) == 2
        
        # Verify user_id is not in response
        assert "user_id" not in data["items"][0]
        
        # Verify PT- ref for other patient
        assert data["items"][0]["patient_ref"] is None
        assert data["items"][1]["patient_ref"] == "PT-OTHER-"





@pytest.mark.asyncio
async def test_delete_report_success(auth_headers):
    mock_supabase_client = MagicMock()
    mock_bucket = AsyncMock()
    mock_supabase_client.storage.from_.return_value = mock_bucket
    mock_bucket.remove.return_value = [{"name": "obj", "error": None}]  # simulated success response
    app.state.supabase_client = mock_supabase_client

    report_id = str(uuid.uuid4())

    # Mock user-scoped SDK client: prefetch returns the owned row; DELETE succeeds.
    mock_user_client = MagicMock()
    mock_select_result = MagicMock()
    mock_select_result.data = [{"storage_path": "path"}]
    mock_user_client.table.return_value.select.return_value.eq.return_value.execute = AsyncMock(return_value=mock_select_result)
    mock_delete_result = MagicMock()
    mock_delete_result.data = []
    mock_user_client.table.return_value.delete.return_value.eq.return_value.execute = AsyncMock(return_value=mock_delete_result)

    from app.core.security import get_current_user
    app.dependency_overrides[get_current_user] = lambda: "test-dev-user"

    with patch("app.api.report_router.make_user_client", new_callable=AsyncMock, return_value=mock_user_client):
        response = client.delete(f"/api/v1/reports/{report_id}", headers={"Authorization": "Bearer test-dev-token-secret"})
        app.dependency_overrides.clear()
        assert response.status_code == 204
        
        # Storage object was removed via the service-role client
        mock_bucket.remove.assert_called_once_with(["path"])
        # SDK DELETE was called
        mock_user_client.table.return_value.delete.return_value.eq.return_value.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_report_refuse_doctor(auth_headers):
    mock_supabase_client = MagicMock()
    mock_bucket = AsyncMock()
    app.state.supabase_client = mock_supabase_client

    report_id = str(uuid.uuid4())

    # Mock user-scoped SDK client: prefetch returns empty (RLS hides the row from non-owner)
    mock_user_client = MagicMock()
    mock_select_result = MagicMock()
    mock_select_result.data = []  # empty — RLS denied visibility
    mock_user_client.table.return_value.select.return_value.eq.return_value.execute = AsyncMock(return_value=mock_select_result)

    from app.core.security import get_current_user
    app.dependency_overrides[get_current_user] = lambda: "test-dev-user"

    with patch("app.api.report_router.make_user_client", new_callable=AsyncMock, return_value=mock_user_client):
        response = client.delete(f"/api/v1/reports/{report_id}", headers={"Authorization": "Bearer test-dev-token-secret"})
        app.dependency_overrides.clear()
        # Even if doctor has care access, they are refused (404 indistinguishable from stranger)
        assert response.status_code == 404
        
        mock_bucket.remove.assert_not_called()
        # SDK DELETE must not have been called
        assert not mock_user_client.table.return_value.delete.called



@pytest.mark.asyncio
async def test_delete_report_storage_fail_leaves_row(auth_headers):
    mock_supabase_client = MagicMock()
    mock_bucket = AsyncMock()
    mock_supabase_client.storage.from_.return_value = mock_bucket
    app.state.supabase_client = mock_supabase_client

    report_id = str(uuid.uuid4())

    # Mock user-scoped SDK client: prefetch always returns the owned row
    mock_user_client = MagicMock()
    mock_select_result = MagicMock()
    mock_select_result.data = [{"storage_path": "path"}]
    mock_user_client.table.return_value.select.return_value.eq.return_value.execute = AsyncMock(return_value=mock_select_result)
    mock_delete_result = MagicMock()
    mock_delete_result.data = []
    mock_user_client.table.return_value.delete.return_value.eq.return_value.execute = AsyncMock(return_value=mock_delete_result)

    from app.core.security import get_current_user
    app.dependency_overrides[get_current_user] = lambda: "test-dev-user"

    with patch("app.api.report_router.make_user_client", new_callable=AsyncMock, return_value=mock_user_client):
        # Case 1: Empty list (object not found — still proceeds to DB delete)
        mock_bucket.remove.return_value = []
        response = client.delete(f"/api/v1/reports/{report_id}", headers={"Authorization": "Bearer test-dev-token-secret"})
        assert response.status_code == 204
        mock_user_client.table.return_value.delete.return_value.eq.return_value.execute.assert_awaited()
        mock_user_client.table.return_value.delete.return_value.eq.return_value.execute.reset_mock()

        # Case 2: List with error dict — storage failed, DB delete must not run
        mock_bucket.remove.return_value = [{"error": "Some storage error"}]
        response = client.delete(f"/api/v1/reports/{report_id}", headers={"Authorization": "Bearer test-dev-token-secret"})
        assert response.status_code == 500
        mock_user_client.table.return_value.delete.return_value.eq.return_value.execute.assert_not_awaited()

        # Case 3: Exception raised by remove
        mock_bucket.remove.side_effect = Exception("Network error")
        response = client.delete(f"/api/v1/reports/{report_id}", headers={"Authorization": "Bearer test-dev-token-secret"})
        assert response.status_code == 500
        mock_user_client.table.return_value.delete.return_value.eq.return_value.execute.assert_not_awaited()

        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_delete_report_not_found_matches_unrelated(auth_headers):
    # Mock user-scoped SDK client: empty prefetch for both cases (not found / wrong owner)
    mock_user_client = MagicMock()
    mock_select_result = MagicMock()
    mock_select_result.data = []
    mock_user_client.table.return_value.select.return_value.eq.return_value.execute = AsyncMock(return_value=mock_select_result)

    from app.core.security import get_current_user
    app.dependency_overrides[get_current_user] = lambda: "test-dev-user"

    with patch("app.api.report_router.make_user_client", new_callable=AsyncMock, return_value=mock_user_client):
        # Case 1: Unrelated user (row exists but RLS hides it — empty prefetch result)
        response_unrelated = client.delete(f"/api/v1/reports/{str(uuid.uuid4())}", headers={"Authorization": "Bearer test-dev-token-secret"})
        
        # Case 2: Nonexistent report_id (row does not exist)
        response_notfound = client.delete(f"/api/v1/reports/{str(uuid.uuid4())}", headers={"Authorization": "Bearer test-dev-token-secret"})
        
        assert response_unrelated.status_code == 404
        assert response_notfound.status_code == 404
        assert response_unrelated.json() == response_notfound.json()
        
        # SDK DELETE must not have been called in either case
        assert not mock_user_client.table.return_value.delete.called

        app.dependency_overrides.clear()
