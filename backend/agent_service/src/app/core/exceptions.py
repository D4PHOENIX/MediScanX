"""Domain-driven exception hierarchy for the agent service."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AgentBaseException(Exception):
    """Base domain exception for the Agentic AI Orchestrator."""

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        context: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        """Initialise the base domain exception.

        Args:
            message (str): A descriptive error message.
            status_code (int, optional): The HTTP status code to return. Defaults to 500.
            context (Optional[Dict[str, Any]], optional): Additional diagnostic context. Defaults to None.
            headers (Optional[Dict[str, str]], optional): HTTP headers to include in the response. Defaults to None.
        """
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.context = context or {}
        self.headers = headers or {}


class LLMInferenceError(AgentBaseException):
    """The LLM provider returned an error or timed out."""

    def __init__(
        self,
        message: str = "LLM inference error",
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialise the LLM inference error.

        Args:
            message (str, optional): A descriptive error message. Defaults to "LLM inference error".
            context (Optional[Dict[str, Any]], optional): Additional diagnostic context. Defaults to None.
        """
        super().__init__(message, status_code=502, context=context)


class ToolExecutionError(AgentBaseException):
    """A registered tool failed during execution."""

    def __init__(
        self,
        message: str = "Tool execution error",
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialise the tool execution error.

        Args:
            message (str, optional): A descriptive error message. Defaults to "Tool execution error".
            context (Optional[Dict[str, Any]], optional): Additional diagnostic context. Defaults to None.
        """
        super().__init__(message, status_code=500, context=context)


class UpstreamServiceUnavailable(AgentBaseException):
    """A downstream medical API is unreachable or returned a non-200 response."""

    def __init__(
        self,
        message: str = "Upstream medical service unavailable",
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialise the upstream service unavailable error.

        Args:
            message (str, optional): A descriptive error message. Defaults to "Upstream medical service unavailable".
            context (Optional[Dict[str, Any]], optional): Additional diagnostic context. Defaults to None.
        """
        super().__init__(message, status_code=503, context=context)


class AgentStateCorrupted(AgentBaseException):
    """The agent's internal state graph is inconsistent."""

    def __init__(
        self,
        message: str = "Agent state corrupted",
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialise the agent state corrupted error.

        Args:
            message (str, optional): A descriptive error message. Defaults to "Agent state corrupted".
            context (Optional[Dict[str, Any]], optional): Additional diagnostic context. Defaults to None.
        """
        super().__init__(message, status_code=500, context=context)


class LLMProviderError(AgentBaseException):
    """The LLM provider encountered an error."""

    def __init__(
        self,
        message: str = "LLM provider error",
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialise the LLM provider error.

        Args:
            message (str, optional): A descriptive error message. Defaults to "LLM provider error".
            context (Optional[Dict[str, Any]], optional): Additional diagnostic context. Defaults to None.
        """
        super().__init__(message, status_code=502, context=context)


class StateGraphExecutionError(AgentBaseException):
    """Error during state graph execution."""

    def __init__(
        self,
        message: str = "State graph execution error",
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialise the state graph execution error.

        Args:
            message (str, optional): A descriptive error message. Defaults to "State graph execution error".
            context (Optional[Dict[str, Any]], optional): Additional diagnostic context. Defaults to None.
        """
        super().__init__(message, status_code=500, context=context)


class ContextRetrievalError(AgentBaseException):
    """Error retrieving clinical context or guidelines."""

    def __init__(
        self,
        message: str = "Context retrieval error",
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialise the context retrieval error.

        Args:
            message (str, optional): A descriptive error message. Defaults to "Context retrieval error".
            context (Optional[Dict[str, Any]], optional): Additional diagnostic context. Defaults to None.
        """
        super().__init__(message, status_code=500, context=context)


class AgentEngineNotReadyError(AgentBaseException):
    """The agent engine is not ready to process requests."""

    def __init__(
        self,
        message: str = "Agent engine not ready",
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialise the agent engine not ready error.

        Args:
            message (str, optional): A descriptive error message. Defaults to "Agent engine not ready".
            context (Optional[Dict[str, Any]], optional): Additional diagnostic context. Defaults to None.
        """
        super().__init__(message, status_code=503, context=context)


class ExceptionRegistry:
    """Maps domain exceptions to structured HTTP responses."""

    @classmethod
    def register_handlers(cls, app: FastAPI) -> None:
        """Install global exception converters on the application.

        Args:
            app (FastAPI): The FastAPI application instance to register handlers on.
        """
        from pydantic import ValidationError

        @app.exception_handler(AgentBaseException)
        async def _handler(
            request: Request, exc: AgentBaseException
        ) -> JSONResponse:
            logger.error(
                "Domain error on %s %s: %s (status=%s) context=%s",
                request.method,
                request.url.path,
                exc.message,
                exc.status_code,
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

        @app.exception_handler(ValidationError)
        async def _validation_handler(
            request: Request, exc: ValidationError
        ) -> JSONResponse:
            logger.warning(
                "Validation error on %s %s: %s",
                request.method,
                request.url.path,
                exc.error_count(),
            )
            return JSONResponse(
                status_code=422,
                content={
                    "error": True,
                    "type": "ValidationError",
                    "message": "Request validation failed",
                    "context": {"errors": exc.errors()},
                },
            )
