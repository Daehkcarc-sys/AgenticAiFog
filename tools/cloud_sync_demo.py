"""Local cloud sync demo for Limon.

Publishes one fog summary through the configured cloud publisher. With default
configuration it writes a versioned event to logs/queues/cloud_events.jsonl. With
CLOUD_SYNC_MODE=kafka and CLOUD_KAFKA_BOOTSTRAP set, it publishes to Kafka.
"""

from __future__ import annotations

from cloud_events import topic_for_event
from cloud_sync import build_cloud_publisher


def main() -> None:
    summary = {
        "sensor_id": "SENSOR_001",
        "trust_score": 0.91,
        "scenario": "Water deficit",
        "severity": "medium",
        "critical": False,
        "decision": "validate",
        "result": "cloud_decided: manual_review",
    }
    publisher = build_cloud_publisher()
    topic = topic_for_event("fog_summary", summary)
    if hasattr(publisher, "publish_event"):
        status = publisher.publish_event("fog_summary", summary, topic)
    else:
        status = publisher.publish(topic, summary)
    print(f"published fog_summary to {topic}: {status}")


if __name__ == "__main__":
    main()
