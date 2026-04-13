"""
Core application instantiation module for the Cloud Backend API and ASGI server entry point.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import logging
from app.core.config import get_settings
from app.api.webhooks import router as webhook_router

# Configure global application logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

class APIFactory:
    """
    A factory class responsible for instantiating, configuring, and yielding the
    FastAPI application instance.
    
    This encapsulates middleware setup, router registration, and configuration 
    injection to prevent global state mutation.
    """
    
    def __init__(self) -> None:
        """
        Initializes the factory state and inject the global configuration singleton.
        """
        self.settings = get_settings()
        self._app: FastAPI | None = None
        
    def _configure_middleware(self, app: FastAPI) -> None:
        """
        Applies security and utility middleware to the application instance.
        
        Args:
            app (FastAPI): The target application instance.
        """
        app.add_middleware(
            CORSMiddleware,
            allow_origins=self.settings.ALLOWED_ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"]
        )
        logger.info("CORS middleware successfully configured.")
    
    def _register_routers(self, app: FastAPI) -> None:
        """
        Mounts modular domain routers to the core application.

        Args:
            app (FastAPI): The target application instance.
        """
        app.include_router(webhook_router, prefix=self.settings.API_PREFIX)
        logger.info(f"Routers registered under prefix: {self.settings.API_PREFIX}")
        
    def _build_app(self) -> FastAPI:
        """
        Constructs the internal FastAPI instance and registers all modular components.

        Returns:
            FastAPI: The fully configured web application ready for ASGI serving.
        """
        app = FastAPI(
            title=self.settings.PROJECT_NAME,
            version=self.settings.VERSION,
            description=self.settings.DESCRIPTION,
            openapi_url=f"{self.settings.API_PREFIX}/openapi.json"
        )
        
        self._configure_middleware(app)
        self._register_routers(app)
        
        logger.info(f"{self.settings.PROJECT_NAME} (v{self.settings.VERSION}) core build complete.")
        return app
        
    def __call__(self) -> FastAPI:
        """
        Dunder method allowing the factory instance to be called directly by ASGI servers.
        Operates as a singleton accessor for the FastAPI instance.

        Returns:
            FastAPI: The cached or newly built application instance.
        """
        if self._app is None:
            self._app = self._build_app()
        return self._app
    
# Function to instantiate the factory and expose the ASGI application
def create_app() -> FastAPI:
    """
    Application factory function for ASGI servers.
    Instantiates the APIFactory and returns the configured FastAPI instance.
    """
    return APIFactory()()

if __name__ == "__main__":
    # Local execution entry point for the development environment
    logger.info("Starting Uvicorn development server...")
    uvicorn.run("app.main:create_app",
                host="0.0.0.0",
                port=8000,
                reload=True,
                factory=True
            )