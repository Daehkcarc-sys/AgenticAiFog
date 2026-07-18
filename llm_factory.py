"""Centralized LLM client factory for all fog-layer agents.

Provides a single configuration point for the language model used across
the pipeline.  This enables:
- One-line model changes for A/B testing
- Centralized API key loading
- Easy mocking in unit tests
- Consistent temperature and model defaults
- Graceful degradation on API failures
"""

from __future__ import annotations

import logging
import os
import time
from functools import lru_cache
from typing import Any

from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv(dotenv_path=Path(__file__).parent / ".env")

logger = logging.getLogger(__name__)

_MAX_RETRIES = 2
_RETRY_DELAY_SECONDS = 2.0


@lru_cache(maxsize=1)
def get_llm(
    model: str | None = None,
    temperature: float = 0.0,
) -> Any:
    """Return a cached ChatGroq instance with the configured defaults.

    The instance is cached via ``lru_cache`` so repeated calls within the
    same process reuse the same client object.

    Args:
        model: Override the default model name.  Defaults to the value of
               ``GROQ_MODEL`` env var or ``llama-3.1-8b-instant``.
        temperature: Sampling temperature (0 = deterministic).

    Returns:
        A configured ``ChatGroq`` instance.
    """
    if model is None:
        model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

    try:
        from langchain_groq import ChatGroq
    except ImportError as exc:
        raise RuntimeError(
            "langchain-groq is required for LLM-backed agents. "
            "Install README dependencies or avoid LLM decision paths."
        ) from exc

    return ChatGroq(
        api_key=os.getenv("GROQ_API_KEY"),
        model=model,
        temperature=temperature,
    )


def safe_invoke(
    system_prompt: str,
    user_message: str,
    fallback: dict[str, Any],
    *,
    max_retries: int = _MAX_RETRIES,
) -> dict[str, Any]:
    """Invoke the LLM with retry logic and graceful fallback.

    On any exception (network, auth, rate-limit, timeout), the call is
    retried up to ``max_retries`` times with exponential backoff.  If
    all retries are exhausted the ``fallback`` dict is returned and the
    error is logged.

    Args:
        system_prompt: The system-level instruction for the LLM.
        user_message: The user-level prompt with sensor data.
        fallback: Dict returned when all retries fail.
        max_retries: Maximum retry attempts (default 2 → 3 total attempts).

    Returns:
        Parsed JSON response dict, or ``fallback`` on persistent failure.
    """
    from utils import safe_parse_json_response

    try:
        from langchain_core.messages import HumanMessage, SystemMessage
    except ImportError as exc:
        logger.error("langchain-core unavailable: %s. Using fallback.", exc)
        return fallback

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_message),
    ]

    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            llm = get_llm()
            response = llm.invoke(messages)
            return safe_parse_json_response(str(response.content), fallback)
        except Exception as exc:
            last_error = exc
            if attempt < max_retries:
                delay = _RETRY_DELAY_SECONDS * (2 ** attempt)
                logger.warning(
                    "LLM call failed (attempt %d/%d): %s. Retrying in %.1fs...",
                    attempt + 1, max_retries + 1, exc, delay,
                )
                time.sleep(delay)
            else:
                logger.error(
                    "LLM call failed after %d attempts: %s. Using fallback.",
                    max_retries + 1, exc,
                )

    return fallback
