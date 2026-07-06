# logger.py
# Audit trail - maps to Runtime Observability & Audit Logs (Figure 1)

import json
import os
from datetime import datetime, timezone

LOG_PATH = "logs/decisions.json"

class FogLogger:

    def __init__(self):
        os.makedirs("logs", exist_ok=True)
        if not os.path.exists(LOG_PATH):
            with open(LOG_PATH, "w") as f:
                json.dump([], f)

    def log(self, sensor_id, trust_score, trust_level,
            decision, result, scenario="N/A", critical=False):

        entry = {
            "logged_at":   datetime.now(timezone.utc).isoformat(),
            "sensor_id":   sensor_id,
            "trust_score": trust_score,
            "trust_level": trust_level,
            "scenario":    scenario,
            "critical":    critical,
            "decision":    decision,
            "result":      result
        }

        with open(LOG_PATH, "r") as f:
            logs = json.load(f)
        logs.append(entry)
        with open(LOG_PATH, "w") as f:
            json.dump(logs, f, indent=2)