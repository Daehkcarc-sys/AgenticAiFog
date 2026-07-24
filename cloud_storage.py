"""SQLite storage for cloud-side fog events and digital twin state."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cloud_events import validate_event
from digital_twin.contracts import FogSummaryContract

DEFAULT_CLOUD_DB_PATH = Path(os.getenv("CLOUD_DB_PATH", "state/cloud_events.db"))
DEFAULT_TWIN_DB_PATH = Path(os.getenv("DIGITAL_TWIN_DB_PATH", "state/digital_twin.db"))


class CloudEventStore:
    """Small real database used by local cloud consumers and dashboard."""

    def __init__(self, path: Path | str = DEFAULT_CLOUD_DB_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def insert_event(self, topic: str, event: dict[str, Any]) -> None:
        validate_event(event)
        payload = event["payload"]
        conn = sqlite3.connect(self.path)
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO cloud_events (
                    event_id, topic, event_type, schema_version, source,
                    created_at, sensor_id, scenario, severity, critical,
                    decision, result, payload_json, ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["event_id"], topic, event["event_type"], event["schema_version"],
                    event["source"], event["created_at"], payload.get("sensor_id"),
                    payload.get("scenario"), payload.get("severity"),
                    int(bool(payload.get("critical", False))), payload.get("decision"),
                    payload.get("result"), json.dumps(payload, sort_keys=True),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def latest_events(self, limit: int = 50) -> list[dict[str, Any]]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM cloud_events ORDER BY ingested_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def summary(self) -> dict[str, Any]:
        conn = sqlite3.connect(self.path)
        try:
            total = conn.execute("SELECT COUNT(*) FROM cloud_events").fetchone()[0]
            by_topic = dict(conn.execute("SELECT topic, COUNT(*) FROM cloud_events GROUP BY topic").fetchall())
            by_type = dict(conn.execute("SELECT event_type, COUNT(*) FROM cloud_events GROUP BY event_type").fetchall())
            critical = conn.execute("SELECT COUNT(*) FROM cloud_events WHERE critical = 1").fetchone()[0]
            return {
                "total_events": total,
                "critical_events": critical,
                "by_topic": by_topic,
                "by_type": by_type,
                "db_path": str(self.path),
            }
        finally:
            conn.close()

    def _init_schema(self) -> None:
        conn = sqlite3.connect(self.path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cloud_events (
                    event_id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    sensor_id TEXT,
                    scenario TEXT,
                    severity TEXT,
                    critical INTEGER NOT NULL DEFAULT 0,
                    decision TEXT,
                    result TEXT,
                    payload_json TEXT NOT NULL,
                    ingested_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cloud_events_topic ON cloud_events(topic)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cloud_events_type ON cloud_events(event_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cloud_events_sensor ON cloud_events(sensor_id)")
            conn.commit()
        finally:
            conn.close()


class DigitalTwinStore:
    """SQLite-backed minimal farm/zone digital twin state."""

    def __init__(self, path: Path | str = DEFAULT_TWIN_DB_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def apply_event(self, topic: str, event: dict[str, Any]) -> None:
        validate_event(event)
        payload = event["payload"]
        summary = FogSummaryContract.from_payload(payload) if event["event_type"] == "fog_summary" else None
        sensor_id = summary.sensor_id if summary else payload.get("sensor_id") or "unknown"
        zone_id = summary.zone_id if summary else payload.get("zone_id") or payload.get("zone") or "default-zone"
        state = {
            "topic": topic,
            "event_type": event["event_type"],
            "scenario": summary.scenario if summary else payload.get("scenario"),
            "severity": summary.severity if summary else payload.get("severity"),
            "critical": summary.critical if summary else bool(payload.get("critical", False)),
            "decision": summary.decision if summary else payload.get("decision"),
            "result": summary.result if summary else payload.get("result"),
            "trust_score": summary.trust_score if summary else payload.get("trust_score"),
            "context_summary": summary.context_summary if summary else payload.get("context_summary"),
            "multimodal_summary": summary.multimodal_summary if summary else payload.get("multimodal_summary"),
        }
        now = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(self.path)
        try:
            conn.execute(
                """
                INSERT INTO twin_events (event_id, topic, zone_id, sensor_id, event_json, applied_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO NOTHING
                """,
                (event["event_id"], topic, zone_id, sensor_id, json.dumps(event, sort_keys=True), now),
            )
            conn.execute(
                """
                INSERT INTO zone_state (zone_id, last_sensor_id, scenario, severity,
                    critical, decision, result, trust_score, context_summary,
                    multimodal_summary, updated_at, state_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(zone_id) DO UPDATE SET
                    last_sensor_id=excluded.last_sensor_id,
                    scenario=excluded.scenario,
                    severity=excluded.severity,
                    critical=excluded.critical,
                    decision=excluded.decision,
                    result=excluded.result,
                    trust_score=excluded.trust_score,
                    context_summary=excluded.context_summary,
                    multimodal_summary=excluded.multimodal_summary,
                    updated_at=excluded.updated_at,
                    state_json=excluded.state_json
                """,
                (
                    zone_id, sensor_id, state["scenario"], state["severity"],
                    int(state["critical"]), state["decision"], state["result"],
                    state["trust_score"], state["context_summary"], state["multimodal_summary"],
                    now, json.dumps(state, sort_keys=True),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def zones(self) -> list[dict[str, Any]]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT * FROM zone_state ORDER BY updated_at DESC").fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def _init_schema(self) -> None:
        conn = sqlite3.connect(self.path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS twin_events (
                    event_id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    zone_id TEXT NOT NULL,
                    sensor_id TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS zone_state (
                    zone_id TEXT PRIMARY KEY,
                    last_sensor_id TEXT,
                    scenario TEXT,
                    severity TEXT,
                    critical INTEGER NOT NULL DEFAULT 0,
                    decision TEXT,
                    result TEXT,
                    trust_score REAL,
                    context_summary TEXT,
                    multimodal_summary TEXT,
                    updated_at TEXT NOT NULL,
                    state_json TEXT NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            conn.close()


