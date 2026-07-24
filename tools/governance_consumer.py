"""Consume cloud governance events and apply local policy/model updates."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from cloud_events import TOPICS, validate_event
from cloud_sync import ModelUpdateStore
from support_services import LocalRuleStore


def apply_governance_event(
    event: dict[str, Any],
    rule_store: LocalRuleStore | None = None,
    model_store: ModelUpdateStore | None = None,
) -> dict[str, Any]:
    validate_event(event)
    rule_store = rule_store or LocalRuleStore()
    model_store = model_store or ModelUpdateStore()
    payload = event["payload"]
    if event["event_type"] == "policy_update":
        return {
            "event_type": "policy_update",
            "status": "applied",
            "policy": rule_store.update(payload),
        }
    if event["event_type"] == "model_update":
        return {
            "event_type": "model_update",
            "status": "installed",
            "model": model_store.install_update(payload),
        }
    raise ValueError(f"unsupported governance event type: {event['event_type']}")


def consume_kafka(bootstrap: str, topics: list[str]) -> None:
    try:
        from kafka import KafkaConsumer
    except ImportError as exc:
        raise RuntimeError("kafka-python is required for governance Kafka consumer") from exc

    consumer = KafkaConsumer(
        *topics,
        bootstrap_servers=bootstrap,
        value_deserializer=lambda raw: json.loads(raw.decode("utf-8")),
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        group_id="fog-governance-consumer",
    )
    for message in consumer:
        result = apply_governance_event(message.value)
        print(json.dumps(result, indent=2))


def consume_jsonl(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        print(json.dumps(apply_governance_event(event), indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jsonl", type=Path, help="Apply governance events from a local JSONL file")
    parser.add_argument("--bootstrap", default=os.getenv("CLOUD_KAFKA_BOOTSTRAP"))
    parser.add_argument("--topics", nargs="*", default=[TOPICS["policy_updates"], TOPICS["model_updates"]])
    args = parser.parse_args()
    if args.jsonl:
        consume_jsonl(args.jsonl)
    elif args.bootstrap:
        consume_kafka(args.bootstrap, args.topics)
    else:
        raise SystemExit("provide --jsonl or CLOUD_KAFKA_BOOTSTRAP")


if __name__ == "__main__":
    main()
