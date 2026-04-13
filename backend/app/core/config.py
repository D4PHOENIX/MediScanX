"""
Core configuration module for the MediScanX API.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class APISettings(BaseSettings):
    """
    Singleton configuration class encapsulating all operational environment variables.
    
    This class leverages Pydantic to enforce strict type-casting at system initialization.
    It serves as the single source of truth for all global configuration.
    """
    PROJECT_NAME: str = "MediScanX Cloud Inference API"
    VERSION: str = "1.0.0"
    API_PREFIX: str = "/api/v1"
    DESCRIPTION: str = "High-throughput RAG and Sync Orchestration API for MediScanX."
    # Infrastructure Credentials
    SUPABASE_URL: str
    SUPABASE_SERVICE_KEY: str
    
    # Pydantic V2 Configuration Dict
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")
    
    # CORS Origins
    ALLOWED_ORIGINS = [
        "http://localhost:3000",
        "http://127.0.0.1:3000"
    ]
    
    def __str__(self) -> str:
        """
        Dunder method providing a secure string representation.
        Deliberately obfuscates cryptographic keys to prevent accidental logging.

        Returns:
            str: A safe representation of the active environment configuration.
        """
        return f"<{self.PROJECT_NAME} Environment | v{self.VERSION}>"
    
@lru_cache()
def get_settings() -> APISettings:
    """
    Instantiates and caches the settings singleton to prevent redundant disk I/O.

    Returns:
        APISettings: The validated application configuration instance.
    """
    return APISettings()
