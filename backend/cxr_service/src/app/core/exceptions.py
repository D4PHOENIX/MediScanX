"""Domain‑specific exceptions for the CXR microservice.

Implements a strict Domain‑Driven Design (DDD) exception hierarchy.
All custom exceptions inherit from a common base, decoupling business logic
from the HTTP layer.  An ExceptionRegistry maps domain errors to
standardized JSON responses when used inside a FastAPI application.
"""

import logging
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

logger: logging.Logger = logging.getLogger(__name__)


class CXRBaseException(Exception):
    """Base class for all CXR domain exceptions.
    
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
        """Initializes the CXRBaseException.

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


# ---------------------------------------------------------------------------
#  Concrete domain exceptions
# ---------------------------------------------------------------------------

class ImageProcessingError(CXRBaseException):
    """Raised when the preprocessing pipeline cannot handle a supplied image."""

    def __init__(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initializes the ImageProcessingError.

        Args:
            message (str): The specific error message.
            context (Optional[Dict[str, Any]], optional): Additional context payload. Defaults to None.
        """
        super().__init__(
            message=message,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            context=context,
        )


class ImageReadError(ImageProcessingError):
    """OpenCV could not read the supplied image file."""

    def __init__(
        self,
        path: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initializes the ImageReadError.

        Args:
            path (str, optional): The path to the file that could not be read. Defaults to "".
            context (Optional[Dict[str, Any]], optional): Additional context payload. Defaults to None.
        """
        ctx: Dict[str, Any] = context or {}
        ctx.setdefault("path", path)
        super().__init__(message=f"Unable to read image at {path}", context=ctx)


class InvalidTensorShapeError(CXRBaseException):
    """The preprocessed tensor does not match the expected shape."""

    def __init__(
        self,
        message: str = "Invalid input tensor shape",
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initializes the InvalidTensorShapeError.

        Args:
            message (str, optional): The specific error message. Defaults to "Invalid input tensor shape".
            context (Optional[Dict[str, Any]], optional): Additional context payload. Defaults to None.
        """
        super().__init__(
            message=message,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            context=context,
        )


class ModelInferenceError(CXRBaseException):
    """PyTorch model forward pass or gradient computation failed."""

    def __init__(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initializes the ModelInferenceError.

        Args:
            message (str): The specific error message.
            context (Optional[Dict[str, Any]], optional): Additional context payload. Defaults to None.
        """
        super().__init__(
            message=message,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            context=context,
        )


class CXRModelNotFoundError(CXRBaseException):
    """Model weights file is missing at the expected path."""

    def __init__(
        self,
        path: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initializes the CXRModelNotFoundError.

        Args:
            path (str, optional): The expected path of the missing weights file. Defaults to "".
            context (Optional[Dict[str, Any]], optional): Additional context payload. Defaults to None.
        """
        ctx: Dict[str, Any] = context or {}
        ctx.setdefault("path", path)
        super().__init__(
            message=f"Model weights not found at {path}",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            context=ctx,
        )


class CXREngineNotReadyError(CXRBaseException):
    """CXR engine hasn't finished initialising – 503 Service Unavailable."""

    def __init__(
        self,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initializes the CXREngineNotReadyError.

        Args:
            context (Optional[Dict[str, Any]], optional): Additional context payload. Defaults to None.
        """
        super().__init__(
            message="CXR engine is still loading or unavailable.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            context=context,
        )


# ---------------------------------------------------------------------------
#  Optional – exception registry for FastAPI integration
# ---------------------------------------------------------------------------

class ExceptionRegistry:
    """Translates domain exceptions into structured HTTP responses."""

    @classmethod
    def register_handlers(cls, app: FastAPI) -> None:
        """Registers global exception handlers on the FastAPI application.

        Args:
            app (FastAPI): The FastAPI application instance to register handlers on.
        """
        @app.exception_handler(CXRBaseException)
        async def _cxr_handler(request: Request, exc: CXRBaseException) -> JSONResponse:
            """Handler for all CXRBaseException domain errors.

            Args:
                request (Request): The incoming HTTP request.
                exc (CXRBaseException): The raised domain exception.

            Returns:
                JSONResponse: A structured JSON response with error details.
            """
            logger.error(
                "CXR domain error at %s: %s | context=%s",
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
