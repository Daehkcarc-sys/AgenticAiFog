"""Storage repositories for local SQLite and production PostgreSQL backends."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol

from cloud_storage import CloudEventStore, DigitalTwinStore
from digital_twin.calibration import CalibrationProfile
from digital_twin.feedback import HumanFeedback
from digital_twin.feedback_store import FeedbackStore


class CloudEventRepository(Protocol):
    def insert_event(self, topic: str, event: dict[str, Any]) -> None: ...
    def latest_events(self, limit: int = 50) -> list[dict[str, Any]]: ...
    def summary(self) -> dict[str, Any]: ...


class TwinStateRepository(Protocol):
    def apply_event(self, topic: str, event: dict[str, Any]) -> None: ...
    def zones(self) -> list[dict[str, Any]]: ...


class FeedbackRepository(Protocol):
    def append(self, feedback: HumanFeedback) -> dict[str, Any]: ...
    def latest(self, limit: int = 50) -> list[dict[str, Any]]: ...
    def export_training_labels(self, output_path: Path | str) -> dict[str, Any]: ...


class CalibrationRepository(Protocol):
    def save(self, profile: CalibrationProfile, active: bool = True) -> None: ...
    def active(self, farm_id: str) -> CalibrationProfile | None: ...


class SQLiteRepositories:
    backend = "sqlite"

    def __init__(
        self,
        cloud_db: str | Path = "state/cloud_events.db",
        twin_db: str | Path = "state/digital_twin.db",
        feedback_path: str | Path = "state/human_feedback.jsonl",
        calibration_dir: str | Path = "state/calibration",
    ) -> None:
        self.cloud_events = CloudEventStore(cloud_db)
        self.twin_state = DigitalTwinStore(twin_db)
        self.feedback = FeedbackStore(feedback_path)
        self.calibration = SQLiteCalibrationRepository(calibration_dir)

    def health(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "cloud": self.cloud_events.summary(),
            "zones": len(self.twin_state.zones()),
            "feedback_labels": len(self.feedback.latest(1000000)),
        }


class SQLiteCalibrationRepository:
    def __init__(self, directory: str | Path = "state/calibration") -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def save(self, profile: CalibrationProfile, active: bool = True) -> None:
        target = self.directory / f"{profile.farm_id}.json"
        payload = profile.to_dict()
        payload["active"] = active
        target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def active(self, farm_id: str) -> CalibrationProfile | None:
        target = self.directory / f"{farm_id}.json"
        if not target.exists():
            return None
        return CalibrationProfile.from_dict(json.loads(target.read_text(encoding="utf-8")))


class PostgresRepositories:
    backend = "postgres"

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.cloud_events = PostgresCloudEventRepository(database_url)
        self.twin_state = PostgresTwinStateRepository(database_url)
        self.feedback = PostgresFeedbackRepository(database_url)
        self.calibration = PostgresCalibrationRepository(database_url)

    def health(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "cloud": self.cloud_events.summary(),
            "zones": len(self.twin_state.zones()),
            "feedback_labels": len(self.feedback.latest(1000000)),
        }


class _PostgresBase:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def _connect(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("Install psycopg first: pip install -r requirements-cloud.txt") from exc
        return psycopg.connect(self.database_url, row_factory=dict_row)


class PostgresCloudEventRepository(_PostgresBase):
    def insert_event(self, topic: str, event: dict[str, Any]) -> None:
        payload = event["payload"]
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO fog_events (
                    event_id, topic, event_type, schema_version, source, created_at,
                    sensor_id, zone_id, scenario, severity, critical, decision, result, payload_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (event_id) DO NOTHING
                """,
                (
                    event["event_id"], topic, event["event_type"], event["schema_version"], event["source"], event["created_at"],
                    payload.get("sensor_id"), payload.get("zone_id") or payload.get("zone"), payload.get("scenario"), payload.get("severity"),
                    bool(payload.get("critical", False)), payload.get("decision"), payload.get("result"), json.dumps(payload),
                ),
            )

    def latest_events(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM fog_events ORDER BY ingested_at DESC LIMIT %s", (limit,)).fetchall()
            return [dict(row) for row in rows]

    def summary(self) -> dict[str, Any]:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS count FROM fog_events").fetchone()["count"]
            critical = conn.execute("SELECT COUNT(*) AS count FROM fog_events WHERE critical = TRUE").fetchone()["count"]
        return {"total_events": total, "critical_events": critical, "backend": "postgres"}


class PostgresTwinStateRepository(_PostgresBase):
    def apply_event(self, topic: str, event: dict[str, Any]) -> None:
        payload = event["payload"]
        zone_id = payload.get("zone_id") or payload.get("zone") or "default-zone"
        sensor_id = payload.get("sensor_id") or "unknown"
        state = {
            "topic": topic,
            "event_type": event["event_type"],
            "scenario": payload.get("scenario"),
            "severity": payload.get("severity"),
            "critical": bool(payload.get("critical", False)),
            "decision": payload.get("decision"),
            "result": payload.get("result"),
            "trust_score": payload.get("trust_score"),
            "context_summary": payload.get("context_summary"),
            "multimodal_summary": payload.get("multimodal_summary"),
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO twin_events (event_id, topic, zone_id, sensor_id, event_json)
                VALUES (%s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (event_id) DO NOTHING
                """,
                (event["event_id"], topic, zone_id, sensor_id, json.dumps(event)),
            )
            conn.execute(
                """
                INSERT INTO zone_state (
                    zone_id, last_sensor_id, scenario, severity, critical, decision,
                    result, trust_score, context_summary, multimodal_summary, state_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (zone_id) DO UPDATE SET
                    last_sensor_id=EXCLUDED.last_sensor_id,
                    scenario=EXCLUDED.scenario,
                    severity=EXCLUDED.severity,
                    critical=EXCLUDED.critical,
                    decision=EXCLUDED.decision,
                    result=EXCLUDED.result,
                    trust_score=EXCLUDED.trust_score,
                    context_summary=EXCLUDED.context_summary,
                    multimodal_summary=EXCLUDED.multimodal_summary,
                    state_json=EXCLUDED.state_json,
                    updated_at=NOW()
                """,
                (
                    zone_id, sensor_id, state["scenario"], state["severity"], state["critical"],
                    state["decision"], state["result"], state["trust_score"], state["context_summary"],
                    state["multimodal_summary"], json.dumps(state),
                ),
            )

    def zones(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT zone_id, last_sensor_id, scenario, severity, decision, updated_at FROM zone_state ORDER BY updated_at DESC"
            ).fetchall()
            return [dict(row) for row in rows]


class PostgresFeedbackRepository(_PostgresBase):
    def append(self, feedback: HumanFeedback) -> dict[str, Any]:
        row = feedback.to_training_label()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO human_feedback (
                    event_id, zone_id, sensor_id, reviewer_id, label, scenario,
                    corrected_action, notes, confidence, feedback_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    row["event_id"], row["zone_id"], row.get("sensor_id"), row["reviewer_id"], row["target"],
                    row.get("scenario"), row.get("corrected_action"), row.get("notes"), row.get("confidence"), json.dumps(row),
                ),
            )
        return row

    def latest(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT feedback_json FROM human_feedback ORDER BY created_at DESC LIMIT %s", (limit,)).fetchall()
            return [row["feedback_json"] for row in rows]

    def export_training_labels(self, output_path: Path | str) -> dict[str, Any]:
        rows = list(reversed(self.latest(1000000)))
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
        return {"schema_version": "1.0", "source": "dashboard_human_feedback", "records": len(rows), "output_path": str(output), "target_column": "target"}


class PostgresCalibrationRepository(_PostgresBase):
    def save(self, profile: CalibrationProfile, active: bool = True) -> None:
        with self._connect() as conn:
            if active:
                conn.execute("UPDATE calibration_profiles SET active = FALSE WHERE farm_id = %s", (profile.farm_id,))
            conn.execute(
                """
                INSERT INTO calibration_profiles (farm_id, source, profile_json, metrics_json, active)
                VALUES (%s, %s, %s::jsonb, %s::jsonb, %s)
                """,
                (profile.farm_id, profile.source, json.dumps(profile.to_dict()), json.dumps(profile.metrics), active),
            )

    def active(self, farm_id: str) -> CalibrationProfile | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT profile_json FROM calibration_profiles WHERE farm_id = %s AND active = TRUE ORDER BY created_at DESC LIMIT 1",
                (farm_id,),
            ).fetchone()
        return CalibrationProfile.from_dict(row["profile_json"]) if row else None


def build_repositories(
    db_backend: str | None = None,
    database_url: str | None = None,
    cloud_db: str | Path = "state/cloud_events.db",
    twin_db: str | Path = "state/digital_twin.db",
    feedback_path: str | Path = "state/human_feedback.jsonl",
) -> SQLiteRepositories | PostgresRepositories:
    backend = (db_backend or os.getenv("DB_BACKEND", "sqlite")).lower()
    if backend == "postgres":
        url = database_url or os.getenv("DATABASE_URL")
        if not url:
            raise ValueError("DATABASE_URL is required when DB_BACKEND=postgres")
        return PostgresRepositories(url)
    if backend != "sqlite":
        raise ValueError(f"unsupported DB_BACKEND: {backend}")
    return SQLiteRepositories(cloud_db=cloud_db, twin_db=twin_db, feedback_path=feedback_path)
