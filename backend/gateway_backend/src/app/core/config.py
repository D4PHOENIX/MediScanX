"""Configuration module for the MediScanX Gateway environment.

Loads and validates foundational operational parameters from environment variables
and `.env` files, providing a strongly-typed and immutable configuration singleton
used throughout the gateway deployment.
"""

from typing import List, Optional
import os

from pydantic import field_validator, Field
from pydantic_settings import BaseSettings


class GatewayConfig(BaseSettings):
    """Immutable configuration contract for the MediScanX Gateway.

    Leverages Pydantic V2 BaseSettings to ingest, validate, and type-cast
    environmental variables into a secure runtime configuration object.

    Attributes:
        supabase_url: The primary endpoint URL for the Supabase backend.
        supabase_publishable_key: The anonymous public key for Supabase access.
        supabase_secret_key: The elevated service role key for administrative Supabase actions.
        dev_mode: A boolean flag activating relaxed security constraints for local development.
        allowed_origins: An explicit list of permitted Cross-Origin Resource Sharing (CORS) origins.
        max_upload_bytes: The maximum permitted size for multipart file uploads, measured in bytes.
        cxr_service_url: The internal network routing URL for the Chest X-Ray inference microservice.
        ecg_service_url: The internal network routing URL for the Electrocardiogram inference microservice.
        skin_service_url: The internal network routing URL for the Dermatological inference microservice.
        agent_service_url: The internal network routing URL for the Agentic AI Orchestrator service.
    """

    supabase_url: str
    supabase_publishable_key: str
    supabase_secret_key: str
    dev_mode: bool = False
    dev_token_secret: str
    database_url: str | None = None

    gemini_api_key: Optional[str] = Field(default_factory=lambda: os.getenv("GEMINI_API_KEY", None))
    google_model: str = Field(default_factory=lambda: os.getenv("GOOGLE_MODEL", "gemini-3.5-flash"))

    # Supabase Storage bucket that holds uploaded scan images.
    # The bucket must exist and have service-role write access.
    supabase_storage_bucket: str

    @property
    def supabase_jwks_url(self) -> str:
        """Constructs the URL for retrieving the JSON Web Key Set (JWKS).

        Returns:
            str: The complete URL endpoint for the Supabase JWKS configuration.
        """
        return f"{self.supabase_url}/auth/v1/.well-known/jwks.json"


    @field_validator("supabase_url")
    @classmethod
    def validate_supabase_url(cls, v: str) -> str:
        """Ensures the Supabase URL is present and well-formed."""
        if not v or not v.strip():
            raise ValueError("SUPABASE_URL cannot be empty")
        from urllib.parse import urlparse
        parsed = urlparse(v)
        if not parsed.scheme or not parsed.netloc or not parsed.scheme.startswith("http"):
            raise ValueError("SUPABASE_URL must be a valid http/https URL")
        return v

    @field_validator("database_url")
    @classmethod
    def validate_database_url_pooler(cls, v: str | None) -> str | None:
        """Ensures the database URL uses the Supabase SESSION pooler (port 5432)."""
        if v:
            from urllib.parse import urlparse
            parsed = urlparse(v)
            if not parsed.hostname or not parsed.hostname.endswith(".pooler.supabase.com"):
                raise ValueError(
                    "DATABASE_URL host must use the .pooler.supabase.com endpoint. "
                    "A bare db.<ref>.supabase.co host resolves to IPv6-only and will fail on IPv4-only networks."
                )
            if parsed.port != 5432:
                raise ValueError(
                    "DATABASE_URL must use the Supabase SESSION pooler (port 5432). "
                    "Session mode supports prepared statements for long-running containers."
                )
        return v

    @property
    def asyncpg_dsn(self) -> str | None:
        """Returns the database URL.

        Since we use the Supabase SESSION pooler (port 5432), prepared statements
        are fully supported and we no longer need to append statement_cache_size=0.

        Returns:
            str | None: The database URL if configured, else None.
        """
        return self.database_url

    # The value is a comma-separated string in the environment, e.g.:
    #   ALLOWED_ORIGINS=https:/abcxyz.app,capacitor://localhost
    allowed_origins: str

    # Upload size cap enforced at the gateway perimeter.
    # 20 MiB covers preprocessed JPEG/PNG; increase for raw DICOM workflows.
    max_upload_bytes: int

    cxr_service_url: str
    ecg_service_url: str
    skin_service_url: str
    agent_service_url: str

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
    }


# Module-level singleton — instantiated once per process at import time.
# All routers import this object instead of calling GatewayConfig() themselves
# (Eliminates per-request and duplicate startup config loads).
gateway_config: GatewayConfig = GatewayConfig()
