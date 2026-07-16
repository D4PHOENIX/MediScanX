"""Configuration module for the MediScanX Gateway environment.

Loads and validates foundational operational parameters from environment variables
and `.env` files, providing a strongly-typed and immutable configuration singleton
used throughout the gateway deployment.
"""

from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings


class GatewayConfig(BaseSettings):
    """Immutable configuration contract for the MediScanX Gateway.

    Leverages Pydantic V2 BaseSettings to ingest, validate, and type-cast
    environmental variables into a secure runtime configuration object.

    Attributes:
        supabase_url: The primary endpoint URL for the Supabase backend.
        supabase_anon_key: The anonymous public key for Supabase access.
        supabase_service_role_key: The elevated service role key for administrative Supabase actions.
        dev_mode: A boolean flag activating relaxed security constraints for local development.
        allowed_origins: An explicit list of permitted Cross-Origin Resource Sharing (CORS) origins.
        max_upload_bytes: The maximum permitted size for multipart file uploads, measured in bytes.
        cxr_service_url: The internal network routing URL for the Chest X-Ray inference microservice.
        ecg_service_url: The internal network routing URL for the Electrocardiogram inference microservice.
        skin_service_url: The internal network routing URL for the Dermatological inference microservice.
        agent_service_url: The internal network routing URL for the Agentic AI Orchestrator service.
    """

    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    dev_mode: bool = False
    dev_token_secret: str
    database_url: str | None = None

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

    @property
    def asyncpg_dsn(self) -> str | None:
        """Returns the database URL with pgBouncer-safe query parameters.

        Supabase uses pgBouncer in transaction mode, which is incompatible
        with asyncpg's default prepared-statement caching.  Appending
        ``statement_cache_size=0`` disables the cache and prevents
        ``prepared statement does not exist`` runtime errors.

        Returns:
            str | None: The DSN string if DATABASE_URL is configured, else None.
        """
        if not self.database_url:
            return None
        separator = "&" if "?" in self.database_url else "?"
        return f"{self.database_url}{separator}statement_cache_size=0"

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
