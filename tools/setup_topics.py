"""Create all Kafka topics required by the fog pipeline.

Usage:
    python -m tools.setup_topics                       # localhost:9092
    python -m tools.setup_topics --bootstrap host:9092
    python -m tools.setup_topics --list                # show topic status only
"""

from __future__ import annotations

import argparse
import sys

from cloud_events import TOPICS
from config import CLOUD_KAFKA_BOOTSTRAP

# Partitions / retention tuned for a single-node dev Redpanda instance.
TOPIC_CONFIG: dict[str, dict] = {
    TOPICS["sensor_data"]:      {"num_partitions": 3, "replication_factor": 1},
    TOPICS["trust_events"]:     {"num_partitions": 1, "replication_factor": 1},
    TOPICS["fog_decisions"]:    {"num_partitions": 2, "replication_factor": 1},
    TOPICS["critical_events"]:  {"num_partitions": 1, "replication_factor": 1},
    TOPICS["model_updates"]:    {"num_partitions": 1, "replication_factor": 1},
    TOPICS["policy_updates"]:   {"num_partitions": 1, "replication_factor": 1},
    TOPICS["dead_letter"]:      {"num_partitions": 1, "replication_factor": 1},
    TOPICS["twin_state"]:       {"num_partitions": 1, "replication_factor": 1},
    TOPICS["twin_sync"]:        {"num_partitions": 1, "replication_factor": 1},
    TOPICS["twin_command"]:     {"num_partitions": 1, "replication_factor": 1},
}


def setup_topics(bootstrap: str, dry_run: bool = False) -> dict[str, str]:
    """Create missing topics; return {topic_name: status}."""
    try:
        from kafka.admin import KafkaAdminClient, NewTopic
        from kafka.errors import TopicAlreadyExistsError
    except ImportError as exc:
        raise SystemExit("kafka-python is required: pip install kafka-python") from exc

    admin = KafkaAdminClient(bootstrap_servers=bootstrap, client_id="fog-setup-topics")
    try:
        existing = set(admin.list_topics())
    except Exception as exc:
        admin.close()
        raise SystemExit(f"Cannot reach Kafka broker at {bootstrap}: {exc}") from exc

    results: dict[str, str] = {}
    to_create = []
    for name, cfg in TOPIC_CONFIG.items():
        if name in existing:
            results[name] = "already_exists"
        elif dry_run:
            results[name] = "would_create"
        else:
            to_create.append(NewTopic(name=name, **cfg))

    if to_create:
        try:
            admin.create_topics(new_topics=to_create, validate_only=False)
            for t in to_create:
                results[t.name] = "created"
        except TopicAlreadyExistsError:
            for t in to_create:
                results[t.name] = "already_exists"
        except Exception as exc:
            admin.close()
            raise SystemExit(f"Failed to create topics: {exc}") from exc

    admin.close()
    return results


def list_topics(bootstrap: str) -> list[str]:
    try:
        from kafka.admin import KafkaAdminClient
    except ImportError as exc:
        raise SystemExit("kafka-python is required: pip install kafka-python") from exc

    admin = KafkaAdminClient(bootstrap_servers=bootstrap, client_id="fog-list-topics")
    try:
        topics = sorted(admin.list_topics())
    finally:
        admin.close()
    return topics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap", default=CLOUD_KAFKA_BOOTSTRAP or "localhost:9092")
    parser.add_argument("--list", action="store_true", help="only list existing topics")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.list:
        topics = list_topics(args.bootstrap)
        if topics:
            for t in topics:
                marker = "✓" if t in TOPIC_CONFIG else " "
                print(f"  [{marker}] {t}")
        else:
            print("  (no topics found)")
        sys.exit(0)

    print(f"Setting up topics on {args.bootstrap} ...")
    results = setup_topics(args.bootstrap, dry_run=args.dry_run)
    pad = max(len(k) for k in results)
    for name, status in sorted(results.items()):
        print(f"  {name:<{pad}}  {status}")
    created = sum(1 for s in results.values() if s == "created")
    print(f"\n{created} topic(s) created, {len(results) - created} already existed.")


if __name__ == "__main__":
    main()
