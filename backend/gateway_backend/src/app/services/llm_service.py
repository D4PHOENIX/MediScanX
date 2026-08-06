"""LLM service for single-shot, non-conversational text generation.

Provides a lightweight HTTP client wrapper around the Gemini REST API,
designed specifically for short, synchronous generations like clinical
correlations and report summaries. Never raises exceptions; always fails open
by returning None to prevent optional AI enrichments from failing the parent request.
"""

import logging
from typing import Optional

from httpx import AsyncClient, HTTPError, Timeout

from app.core.config import gateway_config

logger = logging.getLogger(__name__)


async def generate_hedged_text(prompt: str) -> Optional[str]:
    """Generates a short text completion from the configured LLM.

    Issues a POST request to the Gemini REST API using the model and API key
    from the gateway configuration. Designed for sub-second responses; enforces
    a strict 8.0-second timeout.

    This function never raises an exception. Any failure (timeout, network error,
    non-200 status, missing credentials, malformed JSON, empty response) is caught,
    logged as a warning, and results in a None return value.

    Args:
        prompt: The fully constructed prompt string.

    Returns:
        The generated text string, or None if generation failed or produced no output.
    """
    model = gateway_config.google_model
    api_key = gateway_config.gemini_api_key

    if not api_key:
        logger.warning("generate_hedged_text failed: GEMINI_API_KEY is not configured.")
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ]
    }

    try:
        # Create a transient client. In a high-throughput scenario, reusing the app's
        # global http_client would be preferable, but creating one here isolates it
        # and ensures the 8.0s timeout applies cleanly to this single-shot call.
        async with AsyncClient(timeout=Timeout(8.0)) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            
            data = resp.json()
            candidates = data.get("candidates", [])
            
            if not candidates:
                logger.warning("generate_hedged_text: No candidates returned (possible safety filter block).")
                return None
                
            parts = candidates[0].get("content", {}).get("parts", [])
            if not parts:
                logger.warning("generate_hedged_text: First candidate had no parts.")
                return None
                
            text = parts[0].get("text")
            if text is None:
                logger.warning("generate_hedged_text: First part had no text.")
                return None
                
            return text
            
    except HTTPError as exc:
        logger.warning(
            "generate_hedged_text %s: %s", type(exc).__name__, str(exc) or "(no detail)"
        )
        return None
    except ValueError as exc:
        # Catch JSONDecodeError
        logger.warning(
            "generate_hedged_text %s: %s", type(exc).__name__, str(exc) or "(no detail)"
        )
        return None
    except Exception as exc:
        # Catch-all to ensure we never fail the parent request
        logger.warning(
            "generate_hedged_text %s: %s", type(exc).__name__, str(exc) or "(no detail)"
        )
        return None
