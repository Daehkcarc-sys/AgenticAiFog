# main.py
import pandas as pd
from datetime import datetime, timezone, timedelta
from pipeline import FogPipeline
from dotenv import load_dotenv
from pathlib import Path
import json
import time
import os

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

DATA_PATH = r"data\archive\Crop_recommendationV2.csv"

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
        "anomaly_detected": False
    }

def build_message(row: dict, sensor_id: str, scenario: str = "normal") -> dict:
    raw = {
        "soil_moisture": row.get("soil_moisture"),
        "temperature":   row.get("temperature"),
        "humidity":      row.get("humidity"),
        "rainfall":      row.get("rainfall"),
        "ph":            row.get("ph"),
        "nitrogen":      row.get("N"),
        "phosphorus":    row.get("P"),
        "potassium":     row.get("K"),
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
                "anomaly_detected": False
            }
        }

    return {
        "sensor_id": sensor_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "raw_readings": raw,
        "tinyml_output": fake_tinyml_output(row)
    }

def print_summary():
    with open("logs/decisions.json", "r") as f:
        logs = json.load(f)

    total  = len(logs)
    high   = sum(1 for l in logs if l["trust_level"] == "HIGH")
    medium = sum(1 for l in logs if l["trust_level"] == "MEDIUM")
    low    = sum(1 for l in logs if l["trust_level"] == "LOW")
    critical = sum(1 for l in logs if l.get("critical"))
    actions  = sum(1 for l in logs if "executed" in l["result"])
    rejected = sum(1 for l in logs if "rejected" in l["result"])

    # scenario breakdown
    scenarios = {}
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
    print("-" * 45)
    print(f"  Actions executed   : {actions}")
    print(f"  Rejections         : {rejected}")
    print("-" * 45)
    print("  Scenarios detected:")
    for scenario, count in scenarios.items():
        print(f"    {scenario}: {count}")
    print("=" * 45)

def main():
    # clear log each run
    with open("logs/decisions.json", "w") as f:
        json.dump([], f)

    print("=== Fog Pipeline Starting ===\n")
    df = pd.read_csv(DATA_PATH)
    pipeline = FogPipeline()

    for i, row in df.head(50).iterrows():
        print(f"─── Reading {i+1} ───────────────────────────")
        if i % 7 == 0:
            sensor_id, scenario = "UNKNOWN_999", "normal"
        elif i % 5 == 0:
            sensor_id, scenario = "SENSOR_001", "suspicious"
        else:
            sensor_id, scenario = "SENSOR_001", "normal"

        message = build_message(dict(row), sensor_id, scenario)
        print(f"Sensor: {sensor_id} | Moisture: {message['raw_readings'].get('soil_moisture', 'N/A'):.1f}%")

        result = pipeline.run(message)
        print(f"Result: {result}\n")
        time.sleep(1)

    print_summary()

if __name__ == "__main__":
    main()