import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.storage_service import StorageService

@pytest.mark.asyncio
async def test_storage_upload_correct_bucket_and_path(auth_headers):
    # Mock Supabase async client
    mock_supabase = MagicMock()
    mock_storage = MagicMock()
    mock_bucket = AsyncMock()
    
    mock_supabase.storage = mock_storage
    mock_storage.from_.return_value = mock_bucket
    
    # Setup mock returns
    mock_bucket.get_public_url.return_value = "https://mock-url.com/scan.jpg"
    
    user_id = "user-123"
    scan_id = "scan-456"
    file_bytes = b"fake-image-data"
    content_type = "image/jpeg"
    bucket_name = "test-bucket"
    
    # Call the service
    public_url, storage_path = await StorageService.upload_scan_image(
        supabase_client=mock_supabase,
        bucket=bucket_name,
        user_id=user_id,
        scan_id=scan_id,
        file_bytes=file_bytes,
        content_type=content_type,
    )
    
    assert public_url == "https://mock-url.com/scan.jpg"
    assert storage_path == "user-123/scan-456.jpg"
    
    # Assert bucket selection
    mock_storage.from_.assert_called_once_with("test-bucket")
    
    # Assert upload happens with correct path and parameters
    mock_bucket.upload.assert_awaited_once_with(
        path="user-123/scan-456.jpg",
        file=b"fake-image-data",
        file_options={"content-type": "image/jpeg", "x-upsert": "true"}
    )
