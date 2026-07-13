"""Domain-specific exceptions for the ECG microservice.

Implements a strict Domain-Driven Design (DDD) exception hierarchy.
All custom exceptions inherit from ``ECGBaseException``, decoupling business
logic from the HTTP transport layer. The ``ExceptionRegistry`` maps domain
errors to standardised JSON responses when registered inside a FastAPI app.

Design mirrors the CXR service's exception module exactly — same base class
shape, same registry pattern, same structured JSON response envelope.
"""

import logging
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

logger: logging.Logger = logging.getLogger(__name__)


# =============================================================================
#  Base Exception
# =============================================================================

class ECGBaseException(Exception):
    """Base class for all ECG domain exceptions.
    
    Attributes:
        message (str): The error message.
        status_code (int): The associated HTTP status code.
        context (Dict[str, Any]): Additional context for the error.
        headers (Dict[str, str]): HTTP headers to include in the response.
    """

    def __init__(
        self,
        message: str,
        status_code: int,
        context: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        """Initializes the ECGBaseException.

        Args:
            message (str): The error message description.
            status_code (int): The HTTP status code corresponding to the error.
            context (Optional[Dict[str, Any]], optional): Additional context or payload. Defaults to None.
            headers (Optional[Dict[str, str]], optional): Custom headers for the HTTP response. Defaults to None.
        """
        super().__init__(message)
        self.message: str = message
        self.status_code: int = status_code
        self.context: Dict[str, Any] = context or {}
        self.headers: Dict[str, str] = headers or {}


# =============================================================================
#  Concrete Domain Exceptions
# =============================================================================

class SignalProcessingError(ECGBaseException):
    """Raised when the ECG signal preprocessing pipeline fails.

    Covers both the WFDB digital path and the optical paper-strip path.
    Maps to HTTP 422 Unprocessable Entity — the client supplied a file the
    service cannot interpret as a valid ECG record.
    """

    def __init__(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialise the signal processing error.

        Args:
            message (str): Human-readable error description.
            context (Optional[Dict[str, Any]]): Additional debugging context.
        """
        super().__init__(
            message=message,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            context=context,
        )


class SignalLengthMismatchError(ECGBaseException):
    """Raised when the ECG signal length does not match expected length."""

    def __init__(
        self,
        message: str = "Invalid ECG signal length.",
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialise the signal length mismatch error.

        Args:
            message (str): Error description. Defaults to "Invalid ECG signal length.".
            context (Optional[Dict[str, Any]]): Additional debugging context.
        """
        super().__init__(
            message=message,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            context=context,
        )


class InvalidLeadCountError(ECGBaseException):
    """Raised when the number of ECG leads is invalid."""

    def __init__(
        self,
        message: str = "Invalid number of ECG leads.",
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialise the invalid lead count error.

        Args:
            message (str): Error description. Defaults to "Invalid number of ECG leads.".
            context (Optional[Dict[str, Any]]): Additional debugging context.
        """
        super().__init__(
            message=message,
            status_code=status.HTTP_400_BAD_REQUEST,
            context=context,
        )


class ECGFileReadError(SignalProcessingError):
    """Raised when the supplied WFDB record or image file cannot be opened."""

    def __init__(
        self,
        path: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialise the file read error.

        Args:
            path (str): Filesystem path that could not be read. Defaults to "".
            context (Optional[Dict[str, Any]]): Additional debugging context.
        """
        ctx: Dict[str, Any] = context or {}
        ctx.setdefault("path", path)
        super().__init__(
            message=f"Unable to read ECG file at '{path}'.",
            context=ctx,
        )


class InvalidSignalShapeError(ECGBaseException):
    """Raised when the preprocessed tensor does not match the expected shape.

    Expected shape after preprocessing: (1, 12, 500) — batch × leads × timesteps.
    Maps to HTTP 422 Unprocessable Entity.
    """

    def __init__(
        self,
        message: str = "Invalid ECG signal shape after preprocessing.",
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialise the invalid signal shape error.

        Args:
            message (str): Error description. Defaults to "Invalid ECG signal shape after preprocessing.".
            context (Optional[Dict[str, Any]]): Additional debugging context.
        """
        super().__init__(
            message=message,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            context=context,
        )


class ECGInferenceError(ECGBaseException):
    """Raised when inference fails in either the ONNX or PyTorch backend.

    Covers ONNX Runtime errors, PyTorch forward/backward failures,
    and any unexpected exceptions inside ``run_diagnostic``.
    Maps to HTTP 500 Internal Server Error.
    """

    def __init__(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialise the ECG inference error.

        Args:
            message (str): Error description.
            context (Optional[Dict[str, Any]]): Additional debugging context.
        """
        super().__init__(
            message=message,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            context=context,
        )


class ONNXInferenceError(ECGInferenceError):
    """Raised specifically when the ONNX Runtime session fails during inference."""

    def __init__(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialise the ONNX inference error.

        Args:
            message (str): ONNX Runtime error description.
            context (Optional[Dict[str, Any]]): Additional debugging context (e.g. input shape).
        """
        super().__init__(message=message, context=context)


class ECGModelNotFoundError(ECGBaseException):
    """Raised when model artifacts cannot be located at the configured paths.

    Maps to HTTP 503 Service Unavailable — the container booted but cannot
    serve predictions without the model artifacts.
    """

    def __init__(
        self,
        path: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialise the model not found error.

        Args:
            path (str): The expected path of the missing artifact. Defaults to "".
            context (Optional[Dict[str, Any]]): Additional debugging context.
        """
        ctx: Dict[str, Any] = context or {}
        ctx.setdefault("path", path)
        super().__init__(
            message=f"ECG model artifact not found at '{path}'. "
                    f"Ensure the weights volume is mounted correctly.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            context=ctx,
        )


class ECGEngineNotReadyError(ECGBaseException):
    """Raised when a prediction is requested before the engine has finished
    initialising (i.e. the ONNX session hasn't loaded yet).

    Maps to HTTP 503 Service Unavailable.
    """

    def __init__(
        self,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialise the engine not ready error.

        Args:
            context (Optional[Dict[str, Any]]): Additional debugging context.
        """
        super().__init__(
            message="ECG engine is still loading or unavailable. "
                    "Please retry after the /healthz endpoint returns 200.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            context=context,
        )


# =============================================================================
#  Exception Registry — FastAPI Integration
# =============================================================================

class ExceptionRegistry:
    """Translates ECG domain exceptions into structured HTTP JSON responses.

    Usage::

        from .exceptions import ExceptionRegistry
        ExceptionRegistry.register_handlers(app)

    All ``ECGBaseException`` subclasses are caught by a single handler that
    emits a consistent JSON envelope::

        {
            "error": true,
            "type": "ECGInferenceError",
            "message": "ONNX session produced NaN outputs.",
            "context": {"input_shape": [1, 12, 500]}
        }
    """

    @classmethod
    def register_handlers(cls, app: FastAPI) -> None:
        """Register the domain exception handler on a FastAPI application instance.

        Args:
            app (FastAPI): The FastAPI application to register handlers on.
        """

        @app.exception_handler(ECGBaseException)
        async def _ecg_domain_handler(
            request: Request, exc: ECGBaseException
        ) -> JSONResponse:
            """Exception handler for all ECGBaseException subclasses.

            Args:
                request (Request): The incoming HTTP request.
                exc (ECGBaseException): The raised domain exception.

            Returns:
                JSONResponse: The formatted JSON error response.
            """
            logger.error(
                "ECG domain error at %s: %s | context=%s",
                request.url.path,
                exc.message,
                exc.context,
            )
            return JSONResponse(
                status_code=exc.status_code,
                headers=exc.headers if exc.headers else None,
                content={
                    "error": True,
                    "type": exc.__class__.__name__,
                    "message": exc.message,
                    "context": exc.context,
                },
            )
