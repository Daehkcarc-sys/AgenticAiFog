"""Build reproducible per-client datasets without claiming proxy labels are truth."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from models import CriticalityScenario
from simulation.generator import (
    EventInjection,
    FaultInjection,
    SimulationConfig,
    SyntheticTelemetryGenerator,
)
from simulation.network_model import MarkovConnectivityModel
from simulation.telemetry_schema import SensorFault, TelemetryRecord


SPLIT_NAMES = ("train", "validation", "test")


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    materialized = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in materialized),
        encoding="utf-8",
    )
    return len(materialized)


def _label_distribution(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(str(row["target"]) for row in rows).items()))


def _time_splits(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Split on whole timestamps so the same instant never crosses boundaries."""
    timestamps = sorted({str(row["timestamp"]) for row in rows})
    if len(timestamps) < 3:
        raise ValueError("at least three timestamps per client are required")
    train_end = max(1, int(len(timestamps) * 0.70))
    validation_end = max(train_end + 1, int(len(timestamps) * 0.85))
    validation_end = min(validation_end, len(timestamps) - 1)
    membership = {
        timestamp: (
            "train"
            if index < train_end
            else "validation"
            if index < validation_end
            else "test"
        )
        for index, timestamp in enumerate(timestamps)
    }
    result = {name: [] for name in SPLIT_NAMES}
    for row in rows:
        result[membership[str(row["timestamp"])]].append(row)
    return result


def _stratified_splits(
    rows: list[dict[str, Any]], rng: np.random.Generator
) -> dict[str, list[dict[str, Any]]]:
    """Stratify a static table when no real timestamp exists."""
    by_label: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_label.setdefault(str(row["target"]), []).append(row)
    result = {name: [] for name in SPLIT_NAMES}
    for label_rows in by_label.values():
        order = rng.permutation(len(label_rows))
        shuffled = [label_rows[int(index)] for index in order]
        size = len(shuffled)
        if size == 1:
            result["train"].extend(shuffled)
            continue
        train_end = max(1, int(size * 0.70))
        validation_end = max(train_end, int(size * 0.85))
        if size >= 3:
            validation_end = min(max(train_end + 1, validation_end), size - 1)
        result["train"].extend(shuffled[:train_end])
        result["validation"].extend(shuffled[train_end:validation_end])
        result["test"].extend(shuffled[validation_end:])
    for split_rows in result.values():
        rng.shuffle(split_rows)
    return result


def _flatten_telemetry(record: TelemetryRecord) -> dict[str, Any]:
    return {
        "event_id": record.event_id,
        "device_id": record.device_id,
        "zone_id": record.zone_id,
        "timestamp": record.timestamp.isoformat(),
        "sequence_number": record.sequence_number,
        "features": {
            **record.readings,
            "tinyml_class": record.tinyml_class,
            "tinyml_confidence": record.tinyml_confidence,
            "link_state": record.link_state.value,
            **{f"actuator_{key}": value for key, value in record.actuator_state.items()},
        },
        "sensor_fault_label": record.sensor_fault_label.value,
        "delivered": record.delivered,
        "target": record.event_label.value,
    }


def _cyclic_event_schedule(config: SimulationConfig) -> list[EventInjection]:
    scenarios = list(CriticalityScenario)
    return [
        EventInjection(
            f"zone-{zone_index + 1}",
            scenarios[(step + zone_index * 3) % len(scenarios)],
            step,
            1,
        )
        for step in range(config.steps)
        for zone_index in range(config.zone_count)
    ]


def build_synthetic_federated_dataset(
    output_dir: Path,
    client_count: int = 4,
    seed: int = 5,
    duration_minutes: int = 480,
) -> dict[str, Any]:
    """Create an FL plumbing dataset, explicitly not a real-world benchmark."""
    config = SimulationConfig(
        zone_count=2,
        sensors_per_zone=3,
        duration_minutes=duration_minutes,
        sample_interval_minutes=10,
        seed=seed,
    )
    device_count = config.zone_count * config.sensors_per_zone
    if not 1 <= client_count <= device_count:
        raise ValueError(f"client_count must be between 1 and {device_count}")
    fault_duration = min(4, max(1, config.steps // 8))
    faults = [
        FaultInjection(
            "zone-1-sensor-1",
            SensorFault.GRADUAL_DRIFT,
            max(0, config.steps // 3),
            fault_duration,
            "temperature",
            1.5,
        ),
        FaultInjection(
            "zone-2-sensor-2",
            SensorFault.BURST_LOSS,
            max(0, config.steps * 2 // 3),
            fault_duration,
        ),
    ]
    records = SyntheticTelemetryGenerator(
        config,
        events=_cyclic_event_schedule(config),
        faults=faults,
        connectivity=MarkovConnectivityModel(seed=seed),
    ).generate()
    clients: dict[str, list[dict[str, Any]]] = {
        f"client-{index + 1:02d}": [] for index in range(client_count)
    }
    device_to_client = {
        device_id: f"client-{index % client_count + 1:02d}"
        for index, device_id in enumerate(sorted({record.device_id for record in records}))
    }
    for record in records:
        clients[device_to_client[record.device_id]].append(_flatten_telemetry(record))

    client_manifest: dict[str, Any] = {}
    for client_id, rows in clients.items():
        splits = _time_splits(rows)
        split_metadata: dict[str, Any] = {}
        for split_name, split_rows in splits.items():
            count = _write_jsonl(
                output_dir / client_id / f"{split_name}.jsonl", split_rows
            )
            split_metadata[split_name] = {
                "records": count,
                "labels": _label_distribution(split_rows),
            }
        client_manifest[client_id] = {
            "devices": sorted(
                device for device, owner in device_to_client.items() if owner == client_id
            ),
            "splits": split_metadata,
        }
    manifest = {
        "schema_version": "1.0",
        "source": "seeded_synthetic_telemetry",
        "task_type": "environmental_event_classification",
        "target_column": "target",
        "seed": seed,
        "split_strategy": "chronological_70_15_15_on_whole_timestamps_per_client",
        "client_partition": "device_owner_round_robin",
        "caveats": [
            "Synthetic data validates FL plumbing and failure handling only.",
            "It must not be reported as real-world model effectiveness.",
            "Delivered=false rows model packet loss and should be handled explicitly.",
        ],
        "clients": client_manifest,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def _rebalance_empty_clients(
    clients: list[list[dict[str, Any]]], rng: np.random.Generator
) -> None:
    for empty_index, rows in enumerate(clients):
        if rows:
            continue
        donor_index = max(range(len(clients)), key=lambda index: len(clients[index]))
        donor = clients[donor_index]
        if len(donor) < 2:
            raise ValueError("not enough records to populate every client")
        move_index = int(rng.integers(0, len(donor)))
        clients[empty_index].append(donor.pop(move_index))


def build_crop_proxy_federated_dataset(
    source_archive: Path,
    output_dir: Path,
    client_count: int = 4,
    seed: int = 5,
    dirichlet_alpha: float = 0.5,
) -> dict[str, Any]:
    """Partition the bundled crop table as a proxy, not criticality truth."""
    if client_count < 2:
        raise ValueError("crop proxy requires at least two clients")
    if dirichlet_alpha <= 0:
        raise ValueError("dirichlet_alpha must be positive")
    frame = pd.read_csv(source_archive, compression="zip")
    if "label" not in frame.columns:
        raise ValueError("crop dataset must contain the label column")
    rng = np.random.default_rng(seed)
    clients: list[list[dict[str, Any]]] = [[] for _ in range(client_count)]
    for label, group in frame.groupby("label", sort=True):
        indices = rng.permutation(group.index.to_numpy())
        proportions = rng.dirichlet(np.full(client_count, dirichlet_alpha))
        boundaries = np.cumsum(proportions)[:-1] * len(indices)
        for client_index, allocation in enumerate(
            np.split(indices, boundaries.astype(int))
        ):
            for row_index in allocation:
                row = frame.loc[int(row_index)]
                clients[client_index].append(
                    {
                        "row_id": int(row_index),
                        "features": {
                            column: _json_value(row[column])
                            for column in frame.columns
                            if column != "label"
                        },
                        "target": str(label),
                    }
                )
    _rebalance_empty_clients(clients, rng)
    client_manifest: dict[str, Any] = {}
    for index, rows in enumerate(clients):
        client_id = f"client-{index + 1:02d}"
        splits = _stratified_splits(rows, rng)
        split_metadata: dict[str, Any] = {}
        for split_name, split_rows in splits.items():
            count = _write_jsonl(
                output_dir / client_id / f"{split_name}.jsonl", split_rows
            )
            split_metadata[split_name] = {
                "records": count,
                "labels": _label_distribution(split_rows),
            }
        client_manifest[client_id] = {"splits": split_metadata}
    manifest = {
        "schema_version": "1.0",
        "source": str(source_archive),
        "task_type": "crop_recommendation_proxy",
        "target_column": "target",
        "seed": seed,
        "split_strategy": "stratified_70_15_15_per_client_no_timestamp_available",
        "client_partition": "label_skew_dirichlet",
        "dirichlet_alpha": dirichlet_alpha,
        "caveats": [
            "The crop label is not a Normal/drought/flood/fault ground-truth label.",
            "This dataset cannot validate the project's criticality classifier.",
            "No timestamp or device identity exists, so clients and splits are simulated.",
            "Use it only to start FL infrastructure or a separate crop-recommendation task.",
        ],
        "clients": client_manifest,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def _json_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, np.generic):
        return value.item()
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("synthetic", "crop-proxy"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--clients", type=int, default=4)
    parser.add_argument("--seed", type=int, default=5)
    parser.add_argument("--crop-archive", type=Path, default=Path("data/archive.zip"))
    parser.add_argument("--dirichlet-alpha", type=float, default=0.5)
    args = parser.parse_args()
    if args.source == "synthetic":
        manifest = build_synthetic_federated_dataset(
            args.output, args.clients, args.seed
        )
    else:
        manifest = build_crop_proxy_federated_dataset(
            args.crop_archive,
            args.output,
            args.clients,
            args.seed,
            args.dirichlet_alpha,
        )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()

