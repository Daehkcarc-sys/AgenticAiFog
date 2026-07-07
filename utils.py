from __future__ import annotations

import json
from typing import Any, Dict


def normalize_json_response(response_text: str) -> str:
    cleaned = response_text.strip()
    cleaned = cleaned.replace("```json", "").replace("```", "").strip()
    return cleaned


def parse_json_response(response_text: str) -> Dict[str, Any]:
    cleaned = normalize_json_response(response_text)
    return json.loads(cleaned)


def safe_parse_json_response(response_text: str, fallback: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return parse_json_response(response_text)
    except json.JSONDecodeError:
        return fallback
