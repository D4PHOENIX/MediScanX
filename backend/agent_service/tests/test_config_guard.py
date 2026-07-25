import pytest
import os
from unittest.mock import patch
from app.main import lifespan
from fastapi import FastAPI

@pytest.mark.asyncio
async def test_startup_guard_missing_supabase_url():
    # Remove SUPABASE_URL from environment for this test
    with patch.dict(os.environ, {}, clear=False):
        if "SUPABASE_URL" in os.environ:
            del os.environ["SUPABASE_URL"]
        with pytest.raises(RuntimeError, match="SUPABASE_URL is missing or empty."):
            async with lifespan(FastAPI()):
                pass

@pytest.mark.asyncio
async def test_startup_guard_malformed_supabase_url():
    with patch.dict(os.environ, {"SUPABASE_URL": "not-a-url"}, clear=False):
        with pytest.raises(RuntimeError, match="SUPABASE_URL must be a valid http/https URL."):
            async with lifespan(FastAPI()):
                pass
