"""Separate cloud digital twin service.

Consumes Kafka fog summaries, updates the selected persistence backend, keeps an
in-memory dynamic twin engine for what-if/simulation state, and advances the twin
on a configurable time step. SQLite remains the default backend; PostgreSQL is
selected with DB_BACKEND=postgres and DATABASE_URL.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from typing import Any

from cloud_events import TOPICS, validate_event
from config import CLOUD_KAFKA_BOOTSTRAP
from digital_twin.repositories import build_repositories
from digital_twin.simulator import DigitalTwinEngine

DEFAULT_TOPICS = [TOPICS["sensor_data"], TOPICS["fog_decisions"], TOPICS["critical_events"]]


class DigitalTwinService:
    def __init__(
        self,
        farm_id: str = "demo-farm",
        db_backend: str | None = None,
        database_url: str | None = None,
        simulation_step_minutes: int = 10,
    ) -> None:
        self.repositories = build_repositories(db_backend=db_backend, database_url=database_url)
        calibration = self.repositories.calibration.active(farm_id)
        self.engine = DigitalTwinEngine(farm_id=farm_id, calibration=calibration)
        self.simulation_step_minutes = simulation_step_minutes

    def apply_event(self, topic: str, event: dict[str, Any]) -> dict[str, Any]:
        validate_event(event)
        self.repositories.cloud_events.insert_event(topic, event)
        self.repositories.twin_state.apply_event(topic, event)
        if event["event_type"] == "fog_summary":
            self.engine.apply_fog_summary(event["payload"], event_id=event["event_id"], created_at=event["created_at"])
        return {"status": "applied", "event_id": event["event_id"], "event_type": event["event_type"]}

    def step(self, weather: dict[str, float] | None = None) -> dict[str, Any]:
        result = self.engine.step(minutes=self.simulation_step_minutes, weather=weather)
        return {
            "status": "simulated",
            "step": result.step,
            "simulation_time": result.simulation_time,
            "zones": result.zones,
        }

    def consume_kafka(self, bootstrap: str, topics: list[str], step_every_messages: int = 10) -> None:
        try:
            from kafka import KafkaConsumer
        except ImportError as exc:
            raise SystemExit("Install kafka-python first: pip install -r requirements-cloud.txt") from exc

        consumer = KafkaConsumer(
            *topics,
            bootstrap_servers=bootstrap,
            value_deserializer=lambda raw: json.loads(raw.decode("utf-8")),
            auto_offset_reset="earliest",
            enable_auto_commit=True,
            group_id="agentic-fog-digital-twin-service",
        )
        print(f"digital twin service consuming {topics} from {bootstrap}; backend={type(self.repositories).__name__}")
        count = 0
        for message in consumer:
            print(json.dumps(self.apply_event(message.topic, message.value)))
            count += 1
            if step_every_messages > 0 and count % step_every_messages == 0:
                print(json.dumps(self.step()))

    def run_clock(self, interval_seconds: float = 60.0) -> None:
        print(f"digital twin simulation clock running every {interval_seconds}s")
        while True:
            print(json.dumps(self.step()))
            time.sleep(interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--farm-id", default=os.getenv("FARM_ID", "demo-farm"))
    parser.add_argument("--bootstrap", default=CLOUD_KAFKA_BOOTSTRAP or "localhost:9092")
    parser.add_argument("--topics", nargs="*", default=DEFAULT_TOPICS)
    parser.add_argument("--db-backend", default=os.getenv("DB_BACKEND", "sqlite"))
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--simulation-step-minutes", type=int, default=int(os.getenv("TWIN_SIMULATION_STEP_MINUTES", "10")))
    parser.add_argument("--step-every-messages", type=int, default=int(os.getenv("TWIN_STEP_EVERY_MESSAGES", "10")))
    parser.add_argument("--clock-only", action="store_true")
    parser.add_argument("--clock-interval-seconds", type=float, default=float(os.getenv("TWIN_CLOCK_INTERVAL_SECONDS", "60")))
    args = parser.parse_args()

    service = DigitalTwinService(
        farm_id=args.farm_id,
        db_backend=args.db_backend,
        database_url=args.database_url,
        simulation_step_minutes=args.simulation_step_minutes,
    )
    if args.clock_only:
        service.run_clock(args.clock_interval_seconds)
    else:
        service.consume_kafka(args.bootstrap, args.topics, args.step_every_messages)


if __name__ == "__main__":
    main()
