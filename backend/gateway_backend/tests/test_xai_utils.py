"""Tests for the XAI URL builder utility (Task 4)."""

import pytest

from app.utils.xai_utils import build_xai_authenticated_url
from app.core.config import gateway_config


# ---------------------------------------------------------------------------
# Builder unit tests
# ---------------------------------------------------------------------------

def test_builder_returns_none_for_none():
    """Builder returns None when xai_path is None."""
    assert build_xai_authenticated_url(None) is None


def test_builder_returns_none_for_empty_string():
    """Builder returns None when xai_path is empty string."""
    assert build_xai_authenticated_url("") is None


def test_builder_produces_authenticated_path():
    """Builder produces the authenticated path form, not public or signed."""
    path = "aabbccdd-0000-0000-0000-111111111111/scan123/overlay_0.png"
    url = build_xai_authenticated_url(path)
    assert url is not None
    assert "/authenticated/" in url


def test_builder_preserves_slash_separators():
    """Path separators remain separators — not percent-encoded."""
    path = "user-uuid/scan-uuid/overlay_0.png"
    url = build_xai_authenticated_url(path)
    # The path components must appear verbatim in the URL
    assert "user-uuid/scan-uuid/overlay_0.png" in url


def test_builder_contains_no_public_segment():
    """/public/ must not appear in the URL."""
    path = "user-uuid/scan-uuid/overlay_0.png"
    url = build_xai_authenticated_url(path)
    assert "/public/" not in url


def test_builder_contains_no_signature_or_token():
    """No signed-URL query parameter appears in the output."""
    path = "user-uuid/scan-uuid/overlay_0.png"
    url = build_xai_authenticated_url(path)
    assert "token=" not in url
    assert "?" not in url


def test_builder_uses_supabase_url_from_config():
    """The URL is rooted at the configured supabase_url."""
    path = "user-uuid/scan-uuid/overlay_0.png"
    url = build_xai_authenticated_url(path)
    expected_base = gateway_config.supabase_url.rstrip("/")
    assert url.startswith(expected_base)


def test_builder_includes_bucket_name():
    """The configured bucket name appears in the URL."""
    path = "user-uuid/scan-uuid/overlay_0.png"
    url = build_xai_authenticated_url(path)
    assert gateway_config.supabase_storage_bucket in url


def test_builder_url_form_complete():
    """Full URL matches expected authenticated form."""
    path = "uid/sid/overlay_0.png"
    url = build_xai_authenticated_url(path)
    expected = (
        f"{gateway_config.supabase_url.rstrip('/')}"
        f"/storage/v1/object/authenticated/"
        f"{gateway_config.supabase_storage_bucket}/"
        f"{path}"
    )
    assert url == expected
