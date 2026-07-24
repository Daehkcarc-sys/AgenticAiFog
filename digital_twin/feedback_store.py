"""Persistent local store for dashboard human feedback labels."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from digital_twin.feedback import HumanFeedback


class FeedbackStore:
    """JSONL-backed feedback store used by the local dashboard and ML export."""

    def __init__(self, path: Path | str = "state/human_feedback.jsonl") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, feedback: HumanFeedback) -> dict[str, Any]:
        row = feedback.to_training_label()
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
        return row

    def latest(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return rows[-limit:][::-1]

    def export_training_labels(self, output_path: Path | str) -> dict[str, Any]:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        rows = list(reversed(self.latest(1000000)))
        output.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        return {
            "schema_version": "1.0",
            "source": "dashboard_human_feedback",
            "records": len(rows),
            "output_path": str(output),
            "target_column": "target",
        }
