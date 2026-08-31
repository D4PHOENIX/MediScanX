import pytest
from pydantic import ValidationError
from app.core.config import GatewayConfig
import os

def test_database_url_pooler_accepted():
    # Valid pooler URL
    config = GatewayConfig(
        supabase_url="http://test",
        supabase_publishable_key="test",
        supabase_secret_key="test",
        dev_token_secret="test",
        report_token_secret="test",
        supabase_storage_bucket="test",
        allowed_origins="http://localhost",
        max_upload_bytes=1000,
        cxr_service_url="http://test",
        ecg_service_url="http://test",
        skin_service_url="http://test",
        agent_service_url="http://test",
        android_cert_fingerprints="test-fingerprint",
        database_url="postgresql://user:pass@aws-0-eu-central-1.pooler.supabase.com:5432/postgres"
    )
    assert config.database_url == "postgresql://user:pass@aws-0-eu-central-1.pooler.supabase.com:5432/postgres"

def test_database_url_pooler_rejected_bare_host():
    # Rejected: bare host even on port 5432
    with pytest.raises(ValidationError) as exc:
        GatewayConfig(
            supabase_url="http://test",
            supabase_publishable_key="test",
            supabase_secret_key="test",
            dev_token_secret="test",
            report_token_secret="test",
            supabase_storage_bucket="test",
            allowed_origins="http://localhost",
            max_upload_bytes=1000,
            cxr_service_url="http://test",
            ecg_service_url="http://test",
            skin_service_url="http://test",
            agent_service_url="http://test",
            android_cert_fingerprints="test-fingerprint",
            database_url="postgresql://user:pass@db.xyz.supabase.co:5432/postgres"
        )
    assert "DATABASE_URL host must use the .pooler.supabase.com endpoint" in str(exc.value)

def test_database_url_pooler_rejected_wrong_port():
    # Rejected: non-pooler port
    with pytest.raises(ValidationError) as exc:
        GatewayConfig(
            supabase_url="http://test",
            supabase_publishable_key="test",
            supabase_secret_key="test",
            dev_token_secret="test",
            report_token_secret="test",
            supabase_storage_bucket="test",
            allowed_origins="http://localhost",
            max_upload_bytes=1000,
            cxr_service_url="http://test",
            ecg_service_url="http://test",
            skin_service_url="http://test",
            agent_service_url="http://test",
            android_cert_fingerprints="test-fingerprint",
            database_url="postgresql://user:pass@aws-0-eu-central-1.pooler.supabase.com:5433/postgres"
        )
    assert "DATABASE_URL must use the Supabase SESSION pooler (port 5432)" in str(exc.value)

def test_claim_base_url_from_env(monkeypatch):
    monkeypatch.setenv("CLAIM_BASE_URL", "https://custom.app/claim")
    config = GatewayConfig(
        supabase_url="http://test",
        supabase_publishable_key="test",
        supabase_secret_key="test",
        dev_token_secret="test",
        report_token_secret="test",
        supabase_storage_bucket="test",
        allowed_origins="http://localhost",
        max_upload_bytes=1000,
        cxr_service_url="http://test",
        ecg_service_url="http://test",
        skin_service_url="http://test",
        agent_service_url="http://test",
        android_cert_fingerprints="test-fingerprint"
    )
    assert config.claim_base_url == "https://custom.app/claim"
