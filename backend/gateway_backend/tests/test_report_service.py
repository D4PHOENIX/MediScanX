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
    # Mock supabase
    mock_supabase_client = MagicMock()
    mock_bucket = AsyncMock()
    mock_supabase_client.storage.from_.return_value = mock_bucket
    mock_bucket.create_signed_url.return_value = {"signedURL": "https://signed.mock/report.pdf"}
    mock_bucket.download.return_value = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\xdacd\xf8\xcfP\x0f\x00\x03\x86\x01\x80Z4}k\x00\x00\x00\x00IEND\xaeB`\x82'
    app.state.supabase_client = mock_supabase_client

    # Mock asyncpg
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

    with patch("asyncpg.connect", return_value=mock_conn), \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
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
    mock_supabase_client = MagicMock()
    mock_bucket = AsyncMock()
    mock_supabase_client.storage.from_.return_value = mock_bucket
    mock_bucket.create_signed_url.return_value = {"signedURL": "https://signed.mock/report.pdf"}
    app.state.supabase_client = mock_supabase_client
    
    # Caller requests their own patient_id (no care_relationships check needed)
    patient_id = "test-dev-user"
    file_path = f"{patient_id}_report.pdf"
    
    mock_conn = AsyncMock()
    with patch("asyncpg.connect", return_value=mock_conn):
        response = client.get(
            f"/api/v1/reports/download/{patient_id}",
            headers={"Authorization": "Bearer test-dev-token-secret"},
            follow_redirects=False
        )
        assert response.status_code == 307
        assert response.headers["location"] == "https://signed.mock/report.pdf"
        mock_bucket.create_signed_url.assert_awaited_once_with(file_path, 86400)


@pytest.mark.asyncio
async def test_download_endpoint_unauthorized_is_rejected(auth_headers):
    mock_supabase_client = MagicMock()
    mock_bucket = AsyncMock()
    mock_supabase_client.storage.from_.return_value = mock_bucket
    app.state.supabase_client = mock_supabase_client

    patient_id = "other-patient-id"
    
    mock_conn = AsyncMock()
    # Mock fetchval to return False, signifying no care relationship access
    mock_conn.fetchval.return_value = False
    
    with patch("asyncpg.connect", return_value=mock_conn):
        response = client.get(
            f"/api/v1/reports/download/{patient_id}",
            headers={"Authorization": "Bearer test-dev-token-secret"},
            follow_redirects=False
        )
        assert response.status_code == 403
        assert "Access denied" in response.json()["detail"]
        
        # Assert create_signed_url was never called
        mock_bucket.create_signed_url.assert_not_called()


@patch("app.services.report_service.Paragraph")
def test_pdf_story_contains_xai_status_text(mock_paragraph):
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
    
    # Check that Paragraph was called with the correct text
    called_texts = [call.args[0] for call in mock_paragraph.call_args_list]
    assert any("No heatmap is available for this scan (status: none)" in text for text in called_texts)
    
    # Reset mock for second test
    mock_paragraph.reset_mock()
    
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
    called_texts = [call.args[0] for call in mock_paragraph.call_args_list]
    assert any("Heatmap available but failed to load" in text for text in called_texts)


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


@pytest.mark.asyncio
async def test_download_endpoint_expired_care_relationship_rejected(auth_headers):
    mock_supabase_client = MagicMock()
    app.state.supabase_client = mock_supabase_client

    patient_id = "other-patient-id"
    
    mock_conn = AsyncMock()
    # Mock fetchval to return False (expired relationship)
    mock_conn.fetchval.return_value = False
    
    with patch("asyncpg.connect", return_value=mock_conn):
        response = client.get(
            f"/api/v1/reports/download/{patient_id}",
            headers={"Authorization": "Bearer test-dev-token-secret"},
            follow_redirects=False
        )
        assert response.status_code == 403
        assert "Access denied" in response.json()["detail"]
        
        # Assert the query string includes expires_at
        called_query = mock_conn.fetchval.call_args[0][0]
        assert "expires_at IS NULL OR expires_at > now()" in called_query


@pytest.mark.asyncio
async def test_download_endpoint_null_expiry_granted(auth_headers):
    mock_supabase_client = MagicMock()
    mock_bucket = AsyncMock()
    mock_supabase_client.storage.from_.return_value = mock_bucket
    mock_bucket.create_signed_url.return_value = {"signedURL": "https://signed.mock/report.pdf"}
    app.state.supabase_client = mock_supabase_client

    patient_id = "other-patient-id"
    
    mock_conn = AsyncMock()
    # Mock fetchval to return True (active and indefinite relationship)
    mock_conn.fetchval.return_value = True
    
    with patch("asyncpg.connect", return_value=mock_conn):
        response = client.get(
            f"/api/v1/reports/download/{patient_id}",
            headers={"Authorization": "Bearer test-dev-token-secret"},
            follow_redirects=False
        )
        assert response.status_code == 307
        assert response.headers["location"] == "https://signed.mock/report.pdf"

# ---------------------------------------------------------------------------
# Test 15: PDF Story contains AI Summary when present
# ---------------------------------------------------------------------------

@patch("app.services.report_service.Paragraph")
def test_pdf_story_contains_ai_summary(mock_paragraph):
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
    
    called_texts = [call.args[0] for call in mock_paragraph.call_args_list]
    assert "AI-Generated Clinical Summary" in called_texts
    assert "Test AI summary text" in called_texts
    assert "This summary is AI-generated and may be incomplete or inaccurate. It is not a diagnosis. Discuss these results with a qualified clinician." in called_texts


@patch("app.services.report_service.Paragraph")
def test_pdf_story_omits_ai_summary_when_none(mock_paragraph):
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
    
    called_texts = [call.args[0] for call in mock_paragraph.call_args_list]
    assert "AI-Generated Clinical Summary" not in called_texts
    assert "This summary is AI-generated and may be incomplete or inaccurate. It is not a diagnosis. Discuss these results with a qualified clinician." not in called_texts


@patch("app.services.report_service.SimpleDocTemplate")
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
            mock_canvas.setFillAlpha.assert_called_with(0.15)
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

    with patch("asyncpg.connect", return_value=mock_conn):
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

    mock_conn = AsyncMock()
    # Mock total count
    mock_conn.fetchval.return_value = 2
    # Mock data rows
    report_id1, report_id2 = str(uuid.uuid4()), str(uuid.uuid4())
    mock_conn.fetch.return_value = [
        {"report_id": report_id1, "user_id": "test-dev-user", "created_at": datetime.datetime.now(), "scan_count": 2, "storage_path": "path1"},
        {"report_id": report_id2, "user_id": "other-user-uuid", "created_at": datetime.datetime.now(), "scan_count": 1, "storage_path": "path2"}
    ]

    from app.core.security import get_current_user
    app.dependency_overrides[get_current_user] = lambda: "test-dev-user"

    with patch("asyncpg.connect", return_value=mock_conn):
        response = client.get("/api/v1/reports")
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
        
        # Verify limit and offset behave
        called_query = mock_conn.fetch.call_args[0][0]
        assert "LIMIT $2 OFFSET $3" in called_query
        
        # Verify care relationship expired is explicitly in query
        assert "expires_at IS NULL OR expires_at > now()" in called_query


@pytest.mark.asyncio
async def test_delete_report_success(auth_headers):
    mock_supabase_client = MagicMock()
    mock_bucket = AsyncMock()
    mock_supabase_client.storage.from_.return_value = mock_bucket
    mock_bucket.remove.return_value = [{"name": "obj", "error": None}]  # simulated success response
    app.state.supabase_client = mock_supabase_client

    mock_conn = AsyncMock()
    report_id = str(uuid.uuid4())
    # User owns the report
    mock_conn.fetchrow.return_value = {"user_id": "test-dev-user", "storage_path": "path"}

    from app.core.security import get_current_user
    app.dependency_overrides[get_current_user] = lambda: "test-dev-user"

    with patch("asyncpg.connect", return_value=mock_conn):
        response = client.delete(f"/api/v1/reports/{report_id}")
        app.dependency_overrides.clear()
        assert response.status_code == 204
        
        # Object and row both gone
        mock_bucket.remove.assert_called_once_with(["path"])
        mock_conn.execute.assert_called_once_with("DELETE FROM reports WHERE report_id = $1::uuid", report_id)


@pytest.mark.asyncio
async def test_delete_report_refuse_doctor(auth_headers):
    mock_supabase_client = MagicMock()
    mock_bucket = AsyncMock()
    app.state.supabase_client = mock_supabase_client

    mock_conn = AsyncMock()
    report_id = str(uuid.uuid4())
    # The SQL query filters by user_id = current_user, so if caller is not the owner, fetchrow returns None
    mock_conn.fetchrow.return_value = None

    from app.core.security import get_current_user
    app.dependency_overrides[get_current_user] = lambda: "test-dev-user"

    with patch("asyncpg.connect", return_value=mock_conn):
        response = client.delete(f"/api/v1/reports/{report_id}")
        app.dependency_overrides.clear()
        # Even if doctor has care access, they are refused (404 indistinguishable from stranger)
        assert response.status_code == 404
        
        mock_bucket.remove.assert_not_called()
        mock_conn.execute.assert_not_called()

        called_query = mock_conn.fetchrow.call_args[0][0]
        called_args = mock_conn.fetchrow.call_args[0][1:]
        assert "user_id = $2::uuid" in called_query
        assert called_args == (report_id, "test-dev-user")
        


@pytest.mark.asyncio
async def test_delete_report_storage_fail_leaves_row(auth_headers):
    mock_supabase_client = MagicMock()
    mock_bucket = AsyncMock()
    mock_supabase_client.storage.from_.return_value = mock_bucket
    app.state.supabase_client = mock_supabase_client

    mock_conn = AsyncMock()
    report_id = str(uuid.uuid4())
    mock_conn.fetchrow.return_value = {"user_id": "test-dev-user", "storage_path": "path"}

    from app.core.security import get_current_user
    app.dependency_overrides[get_current_user] = lambda: "test-dev-user"

    with patch("asyncpg.connect", return_value=mock_conn):
        # Case 1: Empty list (object not found)
        mock_bucket.remove.return_value = []
        response = client.delete(f"/api/v1/reports/{report_id}")
        assert response.status_code == 204
        mock_conn.execute.assert_called_once_with("DELETE FROM reports WHERE report_id = $1::uuid", report_id)
        mock_conn.execute.reset_mock()

        # Case 2: List with error dict
        mock_bucket.remove.return_value = [{"error": "Some storage error"}]
        response = client.delete(f"/api/v1/reports/{report_id}")
        assert response.status_code == 500
        mock_conn.execute.assert_not_called()

        # Case 3: Exception raised by remove
        mock_bucket.remove.side_effect = Exception("Network error")
        response = client.delete(f"/api/v1/reports/{report_id}")
        assert response.status_code == 500
        mock_conn.execute.assert_not_called()

        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_delete_report_not_found_matches_unrelated(auth_headers):
    mock_conn = AsyncMock()
    
    from app.core.security import get_current_user
    app.dependency_overrides[get_current_user] = lambda: "test-dev-user"

    with patch("asyncpg.connect", return_value=mock_conn):
        # Case 1: Unrelated user (row exists, but user_id mismatch) - currently our query just returns None
        mock_conn.fetchrow.return_value = None
        response_unrelated = client.delete(f"/api/v1/reports/{str(uuid.uuid4())}")
        
        # Case 2: Nonexistent report_id (row does not exist)
        mock_conn.fetchrow.return_value = None
        response_notfound = client.delete(f"/api/v1/reports/{str(uuid.uuid4())}")
        
        assert response_unrelated.status_code == 404
        assert response_notfound.status_code == 404
        assert response_unrelated.json() == response_notfound.json()
        
        # Verify the query includes the ownership clause
        called_query = mock_conn.fetchrow.call_args[0][0]
        called_args = mock_conn.fetchrow.call_args[0][1:]
        assert "user_id = $2::uuid" in called_query
        assert len(called_args) == 2
        assert called_args[1] == "test-dev-user"

        app.dependency_overrides.clear()
