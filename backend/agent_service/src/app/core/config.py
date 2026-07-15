"""Agent service configuration."""

import os
from dataclasses import dataclass, field
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@dataclass
class AgentConfig:
    """Central configuration for the Agentic AI Orchestrator.

    Reads values from environment variables with sensible defaults for
    local development and containerised deployments to facilitate seamless
    orchestration of clinical AI microservices.

    Attributes:
        gemini_api_key (Optional[str]): API key for accessing Google Gemini services.
        google_project (Optional[str]): Google Cloud project identifier.
        google_credentials_path (Optional[str]): File path to Google Application Credentials JSON.
        supabase_url (Optional[str]): Endpoint URL for the Supabase instance.
        supabase_service_role_key (Optional[str]): Service role key for Supabase administrative access.
        database_url (Optional[str]): PostgreSQL connection string for the primary clinical database.
        cxr_service_url (str): Downstream URL for the Chest X-Ray diagnostic microservice.
        ecg_service_url (str): Downstream URL for the Electrocardiogram analysis microservice.
        skin_service_url (str): Downstream URL for the Dermatological imaging microservice.
        host (str): Host address to bind the agent service to.
        port (int): Port number on which the agent service will listen.
    """

    # LLM API credentials
    gemini_api_key: Optional[str] = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", None))
    google_project: Optional[str] = field(default_factory=lambda: os.getenv("GOOGLE_CLOUD_PROJECT", None))
    google_credentials_path: Optional[str] = field(default_factory=lambda: os.getenv(
        "GOOGLE_APPLICATION_CREDENTIALS", None
    ))
    google_model: str = field(default_factory=lambda: os.getenv("GOOGLE_MODEL", "gemini-3.5-flash"))

    # Supabase / database
    database_url: Optional[str] = field(default_factory=lambda: os.getenv("DATABASE_URL", None))

    # Downstream AI microservice endpoints
    cxr_service_url: str = field(default_factory=lambda: os.getenv(
        "CXR_SERVICE_URL", "http://cxr_service:8001/predict"
    ))
    ecg_service_url: str = field(default_factory=lambda: os.getenv(
        "ECG_SERVICE_URL", "http://ecg_service:8002/predict"
    ))
    skin_service_url: str = field(default_factory=lambda: os.getenv(
        "SKIN_SERVICE_URL", "http://skin_service:8003/predict"
    ))

    # Service settings
    host: str = field(default_factory=lambda: os.getenv("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8005")))
