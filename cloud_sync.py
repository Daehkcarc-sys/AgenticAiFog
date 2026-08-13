"""Cloud synchronization adapters, retry/dead-letter support, and model store."""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import request

from cloud_events import TOPICS, envelope, validate_event
from config import (
    CLOUD_HTTP_ENDPOINT,
    CLOUD_KAFKA_BOOTSTRAP,
    CLOUD_KAFKA_DEAD_LETTER_TOPIC,
    CLOUD_KAFKA_TOPIC,
    CLOUD_PUBLISH_BACKOFF_SECONDS,
    CLOUD_PUBLISH_RETRIES,
    CLOUD_SYNC_MODE,
    MODEL_STORE_PATH,
    QUEUE_DIR,
)


class CloudPublisher:
    def publish(self, topic: str, payload: dict[str, Any]) -> str:
        raise NotImplementedError


class LocalQueuePublisher(CloudPublisher):
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (QUEUE_DIR / "cloud_events.jsonl")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def publish(self, topic: str, payload: dict[str, Any]) -> str:
        event = {
            "topic": topic,
            "payload": payload,
            "queued_at": datetime.now(timezone.utc).isoformat(),
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, sort_keys=True) + "\n")
        return "queued_local"


class HttpPublisher(CloudPublisher):
    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint

    def publish(self, topic: str, payload: dict[str, Any]) -> str:
        body = json.dumps({"topic": topic, "payload": payload}).encode("utf-8")
        req = request.Request(
            self.endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=5) as response:
            if response.status >= 400:
                raise RuntimeError(f"cloud HTTP status {response.status}")
        return "sent_http"


class KafkaPublisher(CloudPublisher):
    """Kafka publisher using kafka-python when installed.

    Keeps a single long-lived KafkaProducer per instance so we don't open
    a new TCP connection for every message.
    """

    def __init__(self, bootstrap_servers: str) -> None:
        self.bootstrap_servers = bootstrap_servers
        self._producer = None

    def _get_producer(self):
        if self._producer is not None:
            return self._producer
        try:
            from kafka import KafkaProducer
        except ImportError as exc:
            raise RuntimeError("kafka-python is required for CLOUD_SYNC_MODE=kafka") from exc
        self._producer = KafkaProducer(
            bootstrap_servers=self.bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            acks="all",
            retries=3,
            linger_ms=5,
        )
        return self._producer

    def publish(self, topic: str, payload: dict[str, Any]) -> str:
        producer = self._get_producer()
        future = producer.send(topic, payload)
        producer.flush(timeout=10)
        future.get(timeout=10)
        return "sent_kafka"

    def close(self) -> None:
        if self._producer is not None:
            self._producer.close()
            self._producer = None


class ReliableCloudPublisher(CloudPublisher):
    """Adds validation, retry/backoff, and local dead-letter fallback."""

    def __init__(
        self,
        inner: CloudPublisher,
        retries: int = CLOUD_PUBLISH_RETRIES,
        backoff_seconds: float = CLOUD_PUBLISH_BACKOFF_SECONDS,
        dead_letter: CloudPublisher | None = None,
        dead_letter_topic: str = CLOUD_KAFKA_DEAD_LETTER_TOPIC,
    ) -> None:
        self.inner = inner
        self.retries = max(0, retries)
        self.backoff_seconds = max(0.0, backoff_seconds)
        self.dead_letter = dead_letter or LocalQueuePublisher(QUEUE_DIR / "cloud_dead_letter.jsonl")
        self.dead_letter_topic = dead_letter_topic

    def publish(self, topic: str, payload: dict[str, Any]) -> str:
        validate_event(payload)
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                return self.inner.publish(topic, payload)
            except Exception as exc:  # noqa: BLE001 - boundary must catch adapter failures
                last_error = exc
                if attempt < self.retries and self.backoff_seconds:
                    time.sleep(self.backoff_seconds * (attempt + 1))
        dead_letter_payload = envelope(
            "dead_letter",
            {
                "failed_topic": topic,
                "failed_event": payload,
                "error": str(last_error),
                "attempts": self.retries + 1,
            },
        )
        self.dead_letter.publish(self.dead_letter_topic, dead_letter_payload)
        return "queued_dead_letter"


class CloudEventPublisher(CloudPublisher):
    """Publishes raw payloads as versioned events with automatic topic routing."""

    def __init__(self, inner: CloudPublisher) -> None:
        self.inner = inner

    def publish_event(self, event_type: str, payload: dict[str, Any], topic: str | None = None) -> str:
        event = envelope(event_type, payload)
        resolved_topic = topic or TOPICS.get(event_type) or CLOUD_KAFKA_TOPIC
        return self.inner.publish(resolved_topic, event)

    def publish(self, topic: str, payload: dict[str, Any]) -> str:
        event_type = payload.get("event_type", "fog_summary") if isinstance(payload, dict) else "fog_summary"
        event = payload if isinstance(payload, dict) and "schema_version" in payload else envelope(event_type, payload)
        return self.inner.publish(topic, event)


def build_cloud_publisher() -> CloudPublisher:
    import os as _os
    mode = (_os.getenv("CLOUD_SYNC_MODE") or CLOUD_SYNC_MODE).lower()
    kafka_bootstrap = _os.getenv("CLOUD_KAFKA_BOOTSTRAP") or CLOUD_KAFKA_BOOTSTRAP
    http_endpoint = _os.getenv("CLOUD_HTTP_ENDPOINT") or CLOUD_HTTP_ENDPOINT
    if mode == "http":
        if not http_endpoint:
            raise ValueError("CLOUD_HTTP_ENDPOINT is required for CLOUD_SYNC_MODE=http")
        base: CloudPublisher = HttpPublisher(http_endpoint)
    elif mode == "kafka":
        if not kafka_bootstrap:
            raise ValueError("CLOUD_KAFKA_BOOTSTRAP is required for CLOUD_SYNC_MODE=kafka")
        base = KafkaPublisher(kafka_bootstrap)
    else:
        base = LocalQueuePublisher()
    return CloudEventPublisher(ReliableCloudPublisher(base))


@dataclass
class ModelVersion:
    version: str
    source_path: str
    checksum_sha256: str
    installed_at: str
    active: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ModelUpdateStore:
    """Durable model metadata with validation, activation, and rollback."""

    def __init__(self, manifest_path: Path | None = None) -> None:
        self.manifest_path = manifest_path or MODEL_STORE_PATH
        self.model_dir = self.manifest_path.parent / "models"
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        if not self.manifest_path.exists():
            self._write({"active_version": None, "versions": []})

    def install_update(self, update: dict[str, Any]) -> dict[str, Any]:
        version = str(update.get("version", "")).strip()
        source = update.get("source_path")
        checksum = update.get("checksum_sha256")
        if not version or not source or not checksum:
            raise ValueError("model update requires version, source_path, checksum_sha256")

        source_path = Path(source)
        if not source_path.exists() or not source_path.is_file():
            raise FileNotFoundError(f"model update source not found: {source_path}")

        actual_checksum = self._sha256(source_path)
        if actual_checksum != checksum:
            raise ValueError("model update checksum mismatch")

        target = self.model_dir / f"{version}{source_path.suffix}"
        shutil.copy2(source_path, target)

        manifest = self._read()
        for item in manifest["versions"]:
            item["active"] = False
        entry = ModelVersion(
            version=version,
            source_path=str(target),
            checksum_sha256=actual_checksum,
            installed_at=datetime.now(timezone.utc).isoformat(),
            active=True,
        ).to_dict()
        manifest["versions"].append(entry)
        manifest["active_version"] = version
        self._write(manifest)
        return entry

    def rollback(self, version: str | None = None) -> dict[str, Any]:
        manifest = self._read()
        versions = manifest["versions"]
        if not versions:
            raise ValueError("no model versions available for rollback")

        target_version = version
        if target_version is None:
            active = manifest.get("active_version")
            previous = [item for item in versions if item["version"] != active]
            if not previous:
                raise ValueError("no previous model version available")
            target_version = previous[-1]["version"]

        found = None
        for item in versions:
            item["active"] = item["version"] == target_version
            if item["active"]:
                found = item
        if found is None:
            raise ValueError(f"model version not found: {target_version}")
        manifest["active_version"] = target_version
        self._write(manifest)
        return found

    def status(self) -> dict[str, Any]:
        return self._read()

    def _read(self) -> dict[str, Any]:
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def _write(self, manifest: dict[str, Any]) -> None:
        self.manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()


DEFAULT_CLOUD_TOPIC = CLOUD_KAFKA_TOPIC

