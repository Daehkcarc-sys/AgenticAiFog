from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from federated.dataset_builder import (
    build_crop_proxy_federated_dataset,
    build_synthetic_federated_dataset,
)


ROOT = Path(__file__).resolve().parents[1]


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class FederatedDatasetBuilderTests(unittest.TestCase):
    def test_synthetic_clients_have_leakage_safe_time_splits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "synthetic"
            manifest = build_synthetic_federated_dataset(
                output, client_count=3, seed=5, duration_minutes=240
            )
            self.assertEqual(manifest["task_type"], "environmental_event_classification")
            self.assertEqual(len(manifest["clients"]), 3)
            event_ids: set[str] = set()
            for client_id in manifest["clients"]:
                split_times: dict[str, set[str]] = {}
                for split in ("train", "validation", "test"):
                    rows = read_jsonl(output / client_id / f"{split}.jsonl")
                    self.assertTrue(rows)
                    split_times[split] = {row["timestamp"] for row in rows}
                    for row in rows:
                        self.assertNotIn(row["event_id"], event_ids)
                        event_ids.add(row["event_id"])
                self.assertTrue(split_times["train"].isdisjoint(split_times["validation"]))
                self.assertTrue(split_times["train"].isdisjoint(split_times["test"]))
                self.assertTrue(split_times["validation"].isdisjoint(split_times["test"]))
                self.assertLess(max(split_times["train"]), min(split_times["validation"]))
                self.assertLess(max(split_times["validation"]), min(split_times["test"]))

    def test_crop_proxy_preserves_every_source_row_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "crop"
            manifest = build_crop_proxy_federated_dataset(
                ROOT / "data" / "archive.zip",
                output,
                client_count=4,
                seed=5,
                dirichlet_alpha=0.5,
            )
            self.assertEqual(manifest["task_type"], "crop_recommendation_proxy")
            self.assertTrue(
                any("cannot validate" in caveat for caveat in manifest["caveats"])
            )
            row_ids: list[int] = []
            for client_id in manifest["clients"]:
                for split in ("train", "validation", "test"):
                    row_ids.extend(
                        row["row_id"]
                        for row in read_jsonl(output / client_id / f"{split}.jsonl")
                    )
            self.assertEqual(len(row_ids), 2200)
            self.assertEqual(len(set(row_ids)), 2200)


if __name__ == "__main__":
    unittest.main()

