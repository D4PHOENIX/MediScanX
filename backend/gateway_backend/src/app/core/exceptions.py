"""Domain-Driven Design (DDD) exception hierarchy for the Gateway Backend.

All custom exceptions derive from `GatewayBaseException`, providing a structured
format for encapsulating HTTP status codes, error messaging, execution contexts,
and response headers. The `ExceptionRegistry` systematically translates these
internal exceptions into standard JSON responses for external consumers.
"""

from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import logging

logger: logging.Logger = logging.getLogger(__name__)


class GatewayBaseException(Exception):
    """Foundational domain exception for the Gateway Backend.

    Provides a standard contract for error propagation across the application,
    ensuring consistent translation to external HTTP responses.

    Attributes:
        message (str): A clear, human-readable description of the error condition.
        status_code (int): The associated HTTP status code to be returned to the client.
        context (Dict[str, Any]): Supplementary metadata providing diagnostic context.
        headers (Dict[str, str]): Optional HTTP headers to accompany the error response.
    """

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        context: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        """Initializes the base gateway exception."""
        super().__init__(message)
        self.message: str = message
        self.status_code: int = status_code
        self.context: Dict[str, Any] = context or {}
        self.headers: Dict[str, str] = headers or {}

    def __repr__(self) -> str:
        """Returns the developer-friendly string representation of the exception."""
        return (
            f"{self.__class__.__name__}("
            f"message={self.message!r}, status_code={self.status_code})"
        )

    def __str__(self) -> str:
        """Returns the user-facing message of the exception."""
        return self.message


class UpstreamServiceError(GatewayBaseException):
    """Exception indicating a downstream microservice failure.

    Raised when a routed inference or orchestration request encounters an
    unreachable destination or returns a non-2xx operational status code.
    """

    def __init__(
        self,
        message: str = "Upstream service error",
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initializes the upstream service error."""
        super().__init__(message, status_code=502, context=context)


class ServiceUnavailableError(GatewayBaseException):
    """Exception indicating a downstream microservice timeout or unavailability.

    Raised when a routed request times out or is actively refused.
    """

    def __init__(
        self,
        message: str = "Service unavailable",
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initializes the service unavailable error."""
        super().__init__(message, status_code=503, context=context)


class AuthenticationFailedError(GatewayBaseException):
    """Exception indicating a failure to cryptographically verify client identity.

    Raised when an incoming request lacks required authorization credentials or
    presents an invalid, expired, or malformed JSON Web Token.
    """

    def __init__(
        self,
        message: str = "Authentication failed",
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initializes the authentication failure error."""
        super().__init__(message, status_code=401, context=context)


class RateLimitExceededError(GatewayBaseException):
    """Exception indicating that the client has surpassed operational quotas.

    Raised when incoming request volume violates configured traffic throttling
    policies, safeguarding upstream services from overload.
    """

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initializes the rate limit exceeded error."""
        super().__init__(message, status_code=429, context=context)


class InvalidPayloadError(GatewayBaseException):
    """Exception indicating structural or semantic validation failure of request data.

    Raised when the provided client payload fails to satisfy established schema
    contracts or type safety requirements.
    """

    def __init__(
        self,
        message: str = "Invalid request payload",
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initializes the payload validation error."""
        super().__init__(message, status_code=422, context=context)


class ExceptionRegistry:
    """Registry for mapping internal domain exceptions to FastApi response pipelines.

    Provides a centralized mechanism to bind exception handlers directly to the
    FastAPI application, ensuring uniformity in error serialization.
    """

    @classmethod
    def register_handlers(cls, app: FastAPI) -> None:
        """Installs global exception conversion middleware onto the application.

        Args:
            app (FastAPI): The target application instance to instrument.
        """

        @app.exception_handler(GatewayBaseException)
        async def _gateway_handler(
            request: Request,
            exc: GatewayBaseException,
        ) -> JSONResponse:
            """Translates domain exceptions into structured JSON responses."""
            logger.error(
                "Gateway error at %s: %s | context=%s",
                request.url.path,
                exc.message,
                exc.context,
            )
            return JSONResponse(
                status_code=exc.status_code,
                content={
                    "error": True,
                    "type": exc.__class__.__name__,
                    "message": exc.message,
                    "context": exc.context,
                },
                headers=exc.headers,
            )

        @app.exception_handler(Exception)
        async def _catchall_handler(request: Request, exc: Exception) -> JSONResponse:
            """Provides a fallback safety net for unhandled system exceptions."""
            logger.exception("Unhandled exception at %s", request.url.path)
            return JSONResponse(
                status_code=500,
                content={
                    "error": True,
                    "type": "InternalServerError",
                    "message": "Internal server error",
                    "context": {},
                },
            )
