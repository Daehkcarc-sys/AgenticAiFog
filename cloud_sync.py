"""Cloud synchronization adapters and local model update store."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import request

from config import (
    CLOUD_HTTP_ENDPOINT,
    CLOUD_KAFKA_BOOTSTRAP,
    CLOUD_KAFKA_TOPIC,
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
    """Kafka publisher using kafka-python when installed."""

    def __init__(self, bootstrap_servers: str) -> None:
        self.bootstrap_servers = bootstrap_servers

    def publish(self, topic: str, payload: dict[str, Any]) -> str:
        try:
            from kafka import KafkaProducer
        except ImportError as exc:
            raise RuntimeError("kafka-python is required for CLOUD_SYNC_MODE=kafka") from exc

        producer = KafkaProducer(
            bootstrap_servers=self.bootstrap_servers,
            value_serializer=lambda value: json.dumps(value).encode("utf-8"),
        )
        producer.send(topic, payload)
        producer.flush(timeout=5)
        producer.close()
        return "sent_kafka"


def build_cloud_publisher() -> CloudPublisher:
    mode = CLOUD_SYNC_MODE.lower()
    if mode == "http":
        if not CLOUD_HTTP_ENDPOINT:
            raise ValueError("CLOUD_HTTP_ENDPOINT is required for CLOUD_SYNC_MODE=http")
        return HttpPublisher(CLOUD_HTTP_ENDPOINT)
    if mode == "kafka":
        if not CLOUD_KAFKA_BOOTSTRAP:
            raise ValueError("CLOUD_KAFKA_BOOTSTRAP is required for CLOUD_SYNC_MODE=kafka")
        return KafkaPublisher(CLOUD_KAFKA_BOOTSTRAP)
    return LocalQueuePublisher()


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
