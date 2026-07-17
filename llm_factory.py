"""Centralized LLM client factory with connectivity awareness.

Provides a single configuration point for the language model used across
the pipeline.  Includes lightweight connectivity probing so the Fog node
can detect external LLM unavailability and switch to deterministic
rule-only operation without crashing.

Features:
- One-line model changes for A/B testing
- Centralized API key loading
- Easy mocking in unit tests
- Graceful degradation on API failures
- Connectivity probing with automatic degraded-mode activation
"""

from __future__ import annotations

import logging
import os
import socket
import time
from functools import lru_cache
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from pathlib import Path

# Load environment once for the entire fog layer
load_dotenv(dotenv_path=Path(__file__).parent / ".env")

logger = logging.getLogger(__name__)

_MAX_RETRIES = 2
_RETRY_DELAY_SECONDS = 2.0
_CONNECTIVITY_CHECK_TIMEOUT = 2.0  # seconds
_CONNECTIVITY_CACHE_SECONDS = 30.0  # re-check interval

# ── Connectivity state ─────────────────────────────────────

_llm_reachable: bool | None = None  # None = not checked yet
_last_connectivity_check: float = 0.0
_degraded_mode_activations: int = 0


def is_llm_reachable() -> bool:
    """Check whether the Groq API endpoint is reachable.

    Uses a lightweight TCP socket probe to api.groq.com:443.  Results
    are cached for ``_CONNECTIVITY_CACHE_SECONDS`` to avoid probing on
    every invocation.
    """
    global _llm_reachable, _last_connectivity_check, _degraded_mode_activations

    now = time.monotonic()
    if _llm_reachable is not None and (now - _last_connectivity_check) < _CONNECTIVITY_CACHE_SECONDS:
        return _llm_reachable

    try:
        socket.create_connection(
            ("api.groq.com", 443),
            timeout=_CONNECTIVITY_CHECK_TIMEOUT,
        ).close()
        _llm_reachable = True
    except (socket.gaierror, socket.timeout, OSError):
        if _llm_reachable is not False:
            _degraded_mode_activations += 1
        _llm_reachable = False
        logger.warning("LLM endpoint unreachable — switching to degraded (rule-only) mode")

    _last_connectivity_check = now
    return _llm_reachable


def connectivity_stats() -> dict[str, Any]:
    """Return connectivity and degraded-mode statistics."""
    return {
        "llm_reachable": _llm_reachable,
        "degraded_mode_activations": _degraded_mode_activations,
        "last_check_seconds_ago": round(time.monotonic() - _last_connectivity_check, 1),
    }


def reset_connectivity_state() -> None:
    """Reset connectivity cache (useful between test runs)."""
    global _llm_reachable, _last_connectivity_check, _degraded_mode_activations
    _llm_reachable = None
    _last_connectivity_check = 0.0
    _degraded_mode_activations = 0


# ── LLM client ─────────────────────────────────────────────


@lru_cache(maxsize=1)
def get_llm(
    model: str | None = None,
    temperature: float = 0.0,
) -> ChatGroq:
    """Return a cached ChatGroq instance."""
    if model is None:
        model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
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
    """Invoke the LLM with retry logic, connectivity check, and graceful fallback.

    If the LLM endpoint is unreachable (detected via TCP probe), the
    call is skipped entirely and ``fallback`` is returned immediately
    — no retries are wasted on a known-unreachable host.

    On any exception (network, auth, rate-limit, timeout), the call is
    retried up to ``max_retries`` times with exponential backoff.
    """
    from utils import safe_parse_json_response

    # Skip retries entirely if endpoint is known unreachable
    if not is_llm_reachable():
        logger.warning("LLM unreachable — returning fallback immediately")
        return fallback

    llm = get_llm()
    messages: list[BaseMessage] = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_message),
    ]

    for attempt in range(max_retries + 1):
        try:
            response = llm.invoke(messages)
            return safe_parse_json_response(str(response.content), fallback)
        except Exception as exc:
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
