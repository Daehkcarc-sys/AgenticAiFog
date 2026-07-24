"""Kafka consumer that applies fog events to the local digital twin store."""

from __future__ import annotations

import argparse
import json

from cloud_events import TOPICS, validate_event
from cloud_storage import DigitalTwinStore
from config import CLOUD_KAFKA_BOOTSTRAP

DEFAULT_TWIN_TOPICS = [
    TOPICS["sensor_data"],
    TOPICS["fog_decisions"],
    TOPICS["critical_events"],
    TOPICS["policy_updates"],
]


def consume(topics: list[str], bootstrap: str, db_path: str | None = None) -> None:
    try:
        from kafka import KafkaConsumer
    except ImportError as exc:
        raise SystemExit("Install kafka-python first: pip install -r requirements-cloud.txt") from exc

    twin = DigitalTwinStore(db_path) if db_path else DigitalTwinStore()
    consumer = KafkaConsumer(
        *topics,
        bootstrap_servers=bootstrap,
        value_deserializer=lambda raw: json.loads(raw.decode("utf-8")),
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        group_id="agentic-fog-digital-twin",
    )
    print(f"digital twin consuming {topics} from {bootstrap}; state db {twin.path}")
    for message in consumer:
        event = message.value
        validate_event(event)
        twin.apply_event(message.topic, event)
        print(f"applied {event['event_type']} {event['event_id']} to twin")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap", default=CLOUD_KAFKA_BOOTSTRAP or "localhost:9092")
    parser.add_argument("--db-path")
    parser.add_argument("--topics", nargs="*", default=DEFAULT_TWIN_TOPICS)
    args = parser.parse_args()
    consume(args.topics, args.bootstrap, args.db_path)


if __name__ == "__main__":
    main()
