"""Cross-cutting fog support services."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import shutil
import socket
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Any
from urllib import request

from config import (
    ACTION_WHITELIST,
    AUDIT_CHAIN_PATH,
    CLOUD_HEALTH_URL,
    CLOUD_KAFKA_BOOTSTRAP,
    LOG_DIR,
    RULE_STORE_PATH,
    SECURITY_HMAC_SECRET,
    SENSOR_REGISTRY,
    TRUST_LEVEL_THRESHOLDS,
)


@dataclass
class ResourceSnapshot:
    cpu_load_1m: float | None
    memory_pressure: float | None
    disk_free_mb: float
    battery_percent: float | None
    network_reachable: bool | None
    constrained: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ResourceMonitor:
    """Collect local resource signals without mandatory third-party packages."""

    def snapshot(self) -> ResourceSnapshot:
        cpu_load = self._cpu_load()
        memory_pressure = self._memory_pressure()
        disk = shutil.disk_usage(Path.cwd())
        disk_free_mb = round(disk.free / (1024 * 1024), 2)
        battery_percent = self._battery_percent()
        network_reachable = self._network_reachable()
        constrained = (
            (cpu_load is not None and cpu_load > max((os.cpu_count() or 1) * 2, 4))
            or (memory_pressure is not None and memory_pressure > 0.90)
            or disk_free_mb < 256
            or (battery_percent is not None and battery_percent < 15)
        )
        return ResourceSnapshot(
            cpu_load_1m=cpu_load,
            memory_pressure=memory_pressure,
            disk_free_mb=disk_free_mb,
            battery_percent=battery_percent,
            network_reachable=network_reachable,
            constrained=constrained,
        )

    @staticmethod
    def _cpu_load() -> float | None:
        if hasattr(os, "getloadavg"):
            try:
                return round(os.getloadavg()[0], 3)
            except OSError:
                return None
        return None

    @staticmethod
    def _memory_pressure() -> float | None:
        try:
            import psutil
        except ImportError:
            return None
        return round(psutil.virtual_memory().percent / 100, 3)

    @staticmethod
    def _battery_percent() -> float | None:
        try:
            import psutil
        except ImportError:
            return None
        battery = psutil.sensors_battery()
        return round(float(battery.percent), 2) if battery else None

    @staticmethod
    def _network_reachable() -> bool | None:
        if not CLOUD_KAFKA_BOOTSTRAP and not CLOUD_HEALTH_URL:
            return None
        try:
            if CLOUD_HEALTH_URL:
                with request.urlopen(CLOUD_HEALTH_URL, timeout=3) as response:
                    return response.status < 500
            host = CLOUD_KAFKA_BOOTSTRAP.split(",")[0].split(":")[0]
            port = int(CLOUD_KAFKA_BOOTSTRAP.split(",")[0].split(":")[1])
            with socket.create_connection((host, port), timeout=3):
                return True
        except Exception:
            return False


class ConnectivityManager:
    """Probe cloud connectivity and track offline state."""

    def __init__(self, offline_after_seconds: float = 120.0) -> None:
        self.offline_after_seconds = offline_after_seconds
        self._last_cloud_success = monotonic()

    def mark_cloud_success(self) -> None:
        self._last_cloud_success = monotonic()

    def probe(self) -> bool:
        if not CLOUD_HEALTH_URL and not CLOUD_KAFKA_BOOTSTRAP:
            return True
        try:
            if CLOUD_HEALTH_URL:
                with request.urlopen(CLOUD_HEALTH_URL, timeout=3) as response:
                    ok = response.status < 500
            else:
                target = CLOUD_KAFKA_BOOTSTRAP.split(",")[0]
                host, port_raw = target.split(":")
                with socket.create_connection((host, int(port_raw)), timeout=3):
                    ok = True
            if ok:
                self.mark_cloud_success()
            return ok
        except Exception:
            return False

    def status(self) -> dict[str, Any]:
        reachable = self.probe()
        age = monotonic() - self._last_cloud_success
        offline = (not reachable) and age > self.offline_after_seconds
        return {
            "cloud_reachable": reachable,
            "last_success_age_seconds": round(age, 3),
            "offline_mode": offline,
        }


class LocalRuleStore:
    """Persistent local rules and policy thresholds."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or RULE_STORE_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write(self._default())

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        data = self._read()
        data["version"] = int(data.get("version", 1)) + 1
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        for key, value in patch.items():
            if key in {"trust_thresholds", "action_whitelist", "rules", "sensor_roles"}:
                data[key] = value
        self._write(data)
        return data

    def to_dict(self) -> dict[str, Any]:
        return self._read()

    def _default(self) -> dict[str, Any]:
        return {
            "version": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "trust_thresholds": dict(TRUST_LEVEL_THRESHOLDS),
            "action_whitelist": list(ACTION_WHITELIST),
            "rules": {
                "low_trust": "reject_and_notify_cloud",
                "medium_trust": "validate_before_actuation",
                "high_trust": "allow_whitelisted_local_action",
            },
            "sensor_roles": {sensor: "field_sensor" for sensor in SENSOR_REGISTRY},
        }

    def _read(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, data: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")


class SecurityAccessControl:
    """HMAC identity verification, role checks, key rotation, audit chain."""

    def __init__(
        self,
        secret: str = SECURITY_HMAC_SECRET,
        audit_path: Path | None = None,
    ) -> None:
        self.secret = secret.encode("utf-8")
        self.audit_path = audit_path or AUDIT_CHAIN_PATH
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)

    def sign_message(self, sensor_id: str, timestamp: str, raw_readings: dict[str, Any]) -> str:
        payload = self._signature_payload(sensor_id, timestamp, raw_readings)
        digest = hmac.new(self.secret, payload, hashlib.sha256).digest()
        return base64.b64encode(digest).decode("ascii")

    def verify_signature(self, sensor_data: dict[str, Any]) -> bool:
        provided = sensor_data.get("signature")
        if not provided:
            return True
        expected = self.sign_message(
            str(sensor_data.get("sensor_id", "")),
            str(sensor_data.get("timestamp", "")),
            sensor_data.get("raw_readings", {}),
        )
        return hmac.compare_digest(str(provided), expected)

    def rotate_key(self, new_secret: str) -> None:
        self.secret = new_secret.encode("utf-8")
        self.append_audit({"event": "key_rotated"})

    def authorize_sensor(self, sensor_id: str | None) -> bool:
        if not isinstance(sensor_id, str):
            return False
        return sensor_id.upper() in {sensor.upper() for sensor in SENSOR_REGISTRY}

    def authorize_action(self, action: str) -> bool:
        return action in ACTION_WHITELIST

    def audit_context(
        self,
        sensor_id: str | None,
        action: str | None = None,
        sensor_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        signature_valid = self.verify_signature(sensor_data or {}) if sensor_data else None
        return {
            "sensor_authorized": self.authorize_sensor(sensor_id),
            "action_authorized": self.authorize_action(action) if action else None,
            "signature_valid": signature_valid,
            "policy": "local_zero_trust_hmac",
        }

    def append_audit(self, event: dict[str, Any]) -> dict[str, Any]:
        previous_hash = self._last_hash()
        entry = {
            "event": event,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "previous_hash": previous_hash,
        }
        entry_hash = hashlib.sha256(
            json.dumps(entry, sort_keys=True).encode("utf-8")
        ).hexdigest()
        entry["hash"] = entry_hash
        with self.audit_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
        return entry

    def verify_audit_chain(self) -> bool:
        previous = "GENESIS"
        if not self.audit_path.exists():
            return True
        with self.audit_path.open("r", encoding="utf-8") as f:
            for line in f:
                entry = json.loads(line)
                entry_hash = entry.pop("hash")
                if entry.get("previous_hash") != previous:
                    return False
                actual = hashlib.sha256(
                    json.dumps(entry, sort_keys=True).encode("utf-8")
                ).hexdigest()
                if actual != entry_hash:
                    return False
                previous = entry_hash
        return True

    def _last_hash(self) -> str:
        if not self.audit_path.exists():
            return "GENESIS"
        lines = [line for line in self.audit_path.read_text(encoding="utf-8").splitlines() if line]
        if not lines:
            return "GENESIS"
        return json.loads(lines[-1])["hash"]

    @staticmethod
    def _signature_payload(sensor_id: str, timestamp: str, raw_readings: dict[str, Any]) -> bytes:
        payload = {
            "sensor_id": sensor_id,
            "timestamp": timestamp,
            "raw_readings": raw_readings,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


class CloudSyncStore:
    """Local durable queue for cloud synchronization."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (LOG_DIR / "cloud_sync_queue.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def enqueue_summary(self, summary: dict[str, Any]) -> None:
        items = self._read()
        items.append(summary)
        self._write(items)

    def drain(self) -> list[dict[str, Any]]:
        items = self._read()
        self._write([])
        return items

    def pending_count(self) -> int:
        return len(self._read())

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []

    def _write(self, items: list[dict[str, Any]]) -> None:
        self.path.write_text(json.dumps(items, indent=2), encoding="utf-8")
