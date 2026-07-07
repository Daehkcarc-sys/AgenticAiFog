from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd

from config import DATA_PATH
from metrics import PipelineMetrics
from pipeline import FogPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-7s] %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


def fake_tinyml_output(row: dict) -> dict:
    soil_moisture = row.get("soil_moisture", 50)
    if soil_moisture < 30:
        action, confidence = "irrigate", 0.90
    elif soil_moisture > 70:
        action, confidence = "stop_irrigation", 0.88
    else:
        action, confidence = "no_action", 0.75

    return {
        "recommended_action": action,
        "confidence": confidence,
        "anomaly_detected": False,
    }


def build_message(row: dict, sensor_id: str, scenario: str = "normal") -> dict:
    raw = {
        "soil_moisture": row.get("soil_moisture"),
        "temperature": row.get("temperature"),
        "humidity": row.get("humidity"),
        "rainfall": row.get("rainfall"),
        "ph": row.get("ph"),
        "nitrogen": row.get("N"),
        "phosphorus": row.get("P"),
        "potassium": row.get("K"),
    }

    if scenario == "suspicious":
        stale = (datetime.now(timezone.utc) - timedelta(seconds=500)).isoformat()
        raw["temperature"] = 999
        raw["humidity"] = 999
        raw["soil_moisture"] = 85
        return {
            "sensor_id": sensor_id,
            "timestamp": stale,
            "raw_readings": raw,
            "tinyml_output": {
                "recommended_action": "irrigate",
                "confidence": 0.95,
                "anomaly_detected": False,
            },
            "scenario": scenario,
        }

    return {
        "sensor_id": sensor_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "raw_readings": raw,
        "tinyml_output": fake_tinyml_output(row),
        "scenario": scenario,
    }


def print_summary() -> None:
    summary_path = Path("logs") / "decisions.json"
    with summary_path.open("r", encoding="utf-8") as f:
        logs = json.load(f)

    total = len(logs)
    high = sum(1 for l in logs if l["trust_level"] == "HIGH")
    medium = sum(1 for l in logs if l["trust_level"] == "MEDIUM")
    low = sum(1 for l in logs if l["trust_level"] == "LOW")
    critical = sum(1 for l in logs if l.get("critical"))
    actions = sum(1 for l in logs if "executed" in l["result"])
    rejected = sum(1 for l in logs if "rejected" in l["result"])
    latencies = [l.get("pipeline_latency_ms", 0.0) for l in logs if isinstance(l.get("pipeline_latency_ms"), (int, float))]
    average_latency = round(sum(latencies) / len(latencies), 2) if latencies else 0.0

    scenarios: dict[str, int] = {}
    for l in logs:
        s = l.get("scenario", "N/A")
        scenarios[s] = scenarios.get(s, 0) + 1

    print("=" * 45)
    print("        FOG AGENT SESSION SUMMARY")
    print("=" * 45)
    print(f"  Total readings     : {total}")
    print(f"  HIGH  (local act)  : {high}")
    print(f"  MEDIUM (validate)  : {medium}")
    print(f"  LOW   (rejected)   : {low}")
    print(f"  Critical events    : {critical}")
    print(f"  Avg latency (ms)   : {average_latency}")
    print("-" * 45)
    print(f"  Actions executed   : {actions}")
    print(f"  Rejections         : {rejected}")
    print("-" * 45)
    print("  Scenarios detected:")
    for scenario, count in scenarios.items():
        print(f"    {scenario}: {count}")
    print("=" * 45)


def main() -> None:
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"Dataset not found: {DATA_PATH}")

    logger.info("=== Fog Pipeline Starting ===")
    df = pd.read_csv(DATA_PATH)
    metrics = PipelineMetrics()
    pipeline = FogPipeline(metrics=metrics)

    log_file = Path("logs") / "decisions.json"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text("[]", encoding="utf-8")

    for i, row in df.head(50).iterrows():
        logger.info("─── Reading %d ───────────────────────────", i + 1)
        if i % 7 == 0:
            sensor_id, scenario = "UNKNOWN_999", "normal"
        elif i % 5 == 0:
            sensor_id, scenario = "SENSOR_001", "suspicious"
        else:
            sensor_id, scenario = "SENSOR_001", "normal"

        message = build_message(dict(row), sensor_id, scenario)
        moisture = message["raw_readings"].get("soil_moisture", float("nan"))
        logger.info("Sensor: %s | Moisture: %.1f%%", sensor_id, moisture)

        result = pipeline.run(message)
        logger.info("Result: %s", result)

    # ── Final reports ──────────────────────────────────────
    print(metrics.report())
    print_summary()

    # Persist metrics for offline analysis / publication figures
    metrics_path = Path("logs") / "metrics.json"
    metrics_path.write_text(json.dumps(metrics.to_dict(), indent=2), encoding="utf-8")
    logger.info("Metrics saved to %s", metrics_path)


if __name__ == "__main__":
    main()
