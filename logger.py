from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from config import LOG_PATH
from models import LogEntry, TrustLevel


class FogLogger:
    """Append-only JSON logger for fog pipeline decisions.

    Caches the log list in memory to avoid O(N²) file I/O: the file is
    read once on first write and kept in memory thereafter.  Each
    ``log()`` call writes the full list atomically so the on-disk file
    is always a valid JSON array.
    """

    def __init__(self, log_path: Path = LOG_PATH):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: list[Dict[str, Any]] | None = None
        if not self.log_path.exists():
            self._write_logs([])

    def _read_logs(self) -> list[Dict[str, Any]]:
        if self._cache is not None:
            return self._cache
        try:
            with self.log_path.open("r", encoding="utf-8") as f:
                self._cache = json.load(f)
                return self._cache
        except (json.JSONDecodeError, FileNotFoundError):
            self._cache = []
            return self._cache

    def _write_logs(self, logs: list[Dict[str, Any]]) -> None:
        with self.log_path.open("w", encoding="utf-8") as f:
            json.dump(logs, f, indent=2)

    def log(
        self,
        sensor_id: str,
        trust_score: float,
        trust_level: TrustLevel | str,
        decision: Dict[str, Any],
        result: str,
        scenario: str = "N/A",
        critical: bool = False,
        additional: Dict[str, Any] | None = None,
    ) -> None:

        if additional is None:
            additional = {}

        entry = LogEntry(
            sensor_id=sensor_id,
            trust_score=trust_score,
            trust_level=trust_level if isinstance(trust_level, TrustLevel) else TrustLevel(trust_level),
            decision=decision,
            result=result,
            scenario=scenario,
            critical=critical,
            additional={"logged_at": datetime.now(timezone.utc).isoformat(), **additional},
        ).to_dict()

        logs = self._read_logs()
        logs.append(entry)
        self._write_logs(logs)
