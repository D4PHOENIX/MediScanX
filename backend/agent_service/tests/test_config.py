"""Tests for AgentConfig."""

import os
from unittest.mock import patch
import pytest

from app.core.config import AgentConfig


def test_agent_config_pooler_url_accepted(auth_headers):
    with patch.dict(os.environ, {"DATABASE_URL": "postgresql://user:pass@aws-0-eu-central-1.pooler.supabase.com:5432/postgres"}):
        config = AgentConfig()
        assert config.database_url == "postgresql://user:pass@aws-0-eu-central-1.pooler.supabase.com:5432/postgres"


def test_agent_config_pooler_url_rejected_bare_host(auth_headers):
    with patch.dict(os.environ, {"DATABASE_URL": "postgresql://user:pass@db.xyz.supabase.co:5432/postgres"}):
        with pytest.raises(ValueError, match="DATABASE_URL host must use the .pooler.supabase.com endpoint"):
            AgentConfig()


def test_agent_config_pooler_url_rejected_wrong_port(auth_headers):
    with patch.dict(os.environ, {"DATABASE_URL": "postgresql://user:pass@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"}):
        with pytest.raises(ValueError, match="DATABASE_URL must use the Supabase SESSION pooler \\(port 5432\\)"):
            AgentConfig()
