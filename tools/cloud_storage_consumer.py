"""Kafka consumer that persists fog cloud events into the configured database backend."""

from __future__ import annotations

import argparse
import json
import os

from cloud_events import TOPICS, validate_event
from config import CLOUD_KAFKA_BOOTSTRAP
from digital_twin.repositories import build_repositories


def consume(
    topics: list[str],
    bootstrap: str,
    db_backend: str | None = None,
    database_url: str | None = None,
    db_path: str | None = None,
) -> None:
    try:
        from kafka import KafkaConsumer
    except ImportError as exc:
        raise SystemExit("Install kafka-python first: pip install -r requirements-cloud.txt") from exc

    repositories = build_repositories(
        db_backend=db_backend,
        database_url=database_url,
        cloud_db=db_path or "state/cloud_events.db",
    )
    store = repositories.cloud_events
    consumer = KafkaConsumer(
        *topics,
        bootstrap_servers=bootstrap,
        value_deserializer=lambda raw: json.loads(raw.decode("utf-8")),
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        group_id="agentic-fog-cloud-storage",
    )
    print(f"consuming {topics} from {bootstrap}; backend={type(repositories).__name__}")
    for message in consumer:
        event = message.value
        validate_event(event)
        store.insert_event(message.topic, event)
        print(f"stored {event['event_type']} {event['event_id']} from {message.topic}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap", default=CLOUD_KAFKA_BOOTSTRAP or "localhost:9092")
    parser.add_argument("--db-backend", default=os.getenv("DB_BACKEND", "sqlite"))
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--db-path")
    parser.add_argument("--topics", nargs="*", default=list(TOPICS.values()))
    args = parser.parse_args()
    consume(args.topics, args.bootstrap, args.db_backend, args.database_url, args.db_path)


if __name__ == "__main__":
    main()
