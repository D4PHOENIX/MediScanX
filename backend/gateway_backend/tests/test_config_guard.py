import pytest
from unittest.mock import patch
from app.core.config import gateway_config
from app.main import lifespan

@pytest.mark.asyncio
async def test_startup_guard_missing_supabase_url():
    with patch.object(gateway_config, 'supabase_url', ''):
        with pytest.raises(RuntimeError, match="SUPABASE_URL is missing or empty."):
            async with lifespan(None):
                pass

@pytest.mark.asyncio
async def test_startup_guard_malformed_supabase_url():
    with patch.object(gateway_config, 'supabase_url', 'not-a-url'):
        with pytest.raises(RuntimeError, match="SUPABASE_URL must be a valid http/https URL."):
            async with lifespan(None):
                pass
