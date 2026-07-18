"""Actuator integration adapters.

Adapters are intentionally small and stdlib-first. Real deployments can choose
HTTP, MQTT, command execution, or local durable queue through config/env vars.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import request

from config import (
    ACTUATOR_COMMAND_TEMPLATE,
    ACTUATOR_HTTP_ENDPOINT,
    ACTUATOR_MODE,
    ACTUATOR_MQTT_HOST,
    ACTUATOR_MQTT_PORT,
    ACTUATOR_MQTT_TOPIC,
    QUEUE_DIR,
)


@dataclass
class ActuationCommand:
    action: str
    context: dict[str, Any]
    issued_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ActuatorAdapter:
    def execute(self, command: ActuationCommand) -> str:
        raise NotImplementedError


class LocalQueueActuator(ActuatorAdapter):
    """Durable file-backed actuator queue for local/edge workers."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (QUEUE_DIR / "actuator_commands.jsonl")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def execute(self, command: ActuationCommand) -> str:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(command.to_dict(), sort_keys=True) + "\n")
        return f"{command.action}_queued"


class HttpActuator(ActuatorAdapter):
    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint

    def execute(self, command: ActuationCommand) -> str:
        payload = json.dumps(command.to_dict()).encode("utf-8")
        req = request.Request(
            self.endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=5) as response:
            if response.status >= 400:
                raise RuntimeError(f"actuator HTTP status {response.status}")
        return f"{command.action}_sent_http"


class CommandActuator(ActuatorAdapter):
    def __init__(self, template: str) -> None:
        self.template = template

    def execute(self, command: ActuationCommand) -> str:
        rendered = self.template.format(action=command.action)
        completed = subprocess.run(
            rendered.split(),
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return completed.stdout.strip() or f"{command.action}_command_executed"


class MqttActuator(ActuatorAdapter):
    """MQTT adapter using paho-mqtt when installed."""

    def __init__(self, host: str, port: int, topic: str) -> None:
        self.host = host
        self.port = port
        self.topic = topic

    def execute(self, command: ActuationCommand) -> str:
        try:
            import paho.mqtt.client as mqtt
        except ImportError as exc:
            raise RuntimeError("paho-mqtt is required for ACTUATOR_MODE=mqtt") from exc

        client = mqtt.Client()
        client.connect(self.host, self.port, keepalive=30)
        client.publish(self.topic, json.dumps(command.to_dict()), qos=1)
        client.disconnect()
        return f"{command.action}_sent_mqtt"


def build_actuator_adapter() -> ActuatorAdapter:
    mode = ACTUATOR_MODE.lower()
    if mode == "http":
        if not ACTUATOR_HTTP_ENDPOINT:
            raise ValueError("ACTUATOR_HTTP_ENDPOINT is required for ACTUATOR_MODE=http")
        return HttpActuator(ACTUATOR_HTTP_ENDPOINT)
    if mode == "mqtt":
        if not ACTUATOR_MQTT_HOST:
            raise ValueError("ACTUATOR_MQTT_HOST is required for ACTUATOR_MODE=mqtt")
        return MqttActuator(ACTUATOR_MQTT_HOST, ACTUATOR_MQTT_PORT, ACTUATOR_MQTT_TOPIC)
    if mode == "command":
        if not ACTUATOR_COMMAND_TEMPLATE:
            raise ValueError("ACTUATOR_COMMAND_TEMPLATE is required for ACTUATOR_MODE=command")
        return CommandActuator(ACTUATOR_COMMAND_TEMPLATE)
    return LocalQueueActuator()


def make_command(action: str, context: dict[str, Any] | None = None) -> ActuationCommand:
    return ActuationCommand(
        action=action,
        context=context or {},
        issued_at=datetime.now(timezone.utc).isoformat(),
    )
