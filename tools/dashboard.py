"""Dashboard/API for cloud event, digital twin, and feedback repositories."""

from __future__ import annotations

import argparse
import html
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from cloud_events import TOPICS
from config import CLOUD_KAFKA_BOOTSTRAP
from digital_twin.feedback import HumanFeedback
from digital_twin.optimization import IrrigationOptimizer
from digital_twin.repositories import build_repositories


class DashboardHandler(BaseHTTPRequestHandler):
    repositories: object
    feedback_export_path: str = "data/human_feedback_labels.jsonl"
    audit_path: Path = Path("logs/dashboard_audit.jsonl")
    read_token: str | None = None
    write_token: str | None = None
    admin_token: str | None = None

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        required_role = "admin" if path == "/api/feedback/export" else "read"
        if not self._authorized(parsed.query, required_role):
            self._unauthorized()
            return
        if path == "/api/events":
            self._json(self.repositories.cloud_events.latest_events(100))
            return
        if path == "/api/summary":
            self._json(self.repositories.cloud_events.summary())
            return
        if path == "/api/twin":
            self._json(self.repositories.twin_state.zones())
            return
        if path == "/api/feedback":
            self._json(self.repositories.feedback.latest(100))
            return
        if path == "/api/feedback/export":
            result = self.repositories.feedback.export_training_labels(self.feedback_export_path)
            self._audit("feedback_export", required_role, {"output_path": result["output_path"]})
            self._json(result)
            return
        if path == "/api/health":
            self._json(self._health())
            return
        if path == "/api/optimize/irrigation":
            self._json([rec.__dict__ for rec in IrrigationOptimizer().recommend(self.repositories.twin_state.zones())])
            return
        self._html(self._render_page())

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if not self._authorized(parsed.query, "write"):
            self._unauthorized()
            return
        if parsed.path != "/api/feedback":
            self._json_error(404, "unknown endpoint")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            feedback = HumanFeedback(
                event_id=str(payload["event_id"]),
                zone_id=str(payload["zone_id"]),
                reviewer_id=str(payload["reviewer_id"]),
                label=str(payload["label"]),
                sensor_id=_optional_str(payload.get("sensor_id")),
                scenario=_optional_str(payload.get("scenario")),
                corrected_action=_optional_str(payload.get("corrected_action")),
                notes=_optional_str(payload.get("notes")),
                confidence=_optional_float(payload.get("confidence")),
            )
        except Exception as exc:
            self._json_error(400, f"invalid feedback: {exc}")
            return
        stored = self.repositories.feedback.append(feedback)
        self._audit("feedback_append", "write", {"event_id": stored["event_id"], "zone_id": stored["zone_id"]})
        self._json({"status": "stored", "feedback": stored})

    def log_message(self, format: str, *args: object) -> None:
        return

    def _authorized(self, query: str, required_role: str) -> bool:
        tokens = self._tokens_for_role(required_role)
        if not any(tokens):
            return True
        supplied = self._supplied_token(query)
        return supplied in {token for token in tokens if token}

    def _tokens_for_role(self, role: str) -> list[str | None]:
        if role == "admin":
            return [self.admin_token]
        if role == "write":
            return [self.write_token, self.admin_token]
        return [self.read_token, self.write_token, self.admin_token]

    def _supplied_token(self, query: str) -> str | None:
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header.removeprefix("Bearer ")
        return parse_qs(query).get("token", [None])[0]

    def _unauthorized(self) -> None:
        body = b"unauthorized\n"
        self.send_response(401)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("WWW-Authenticate", "Bearer")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: object) -> None:
        body = json.dumps(payload, indent=2, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json_error(self, status: int, message: str) -> None:
        body = json.dumps({"error": message}, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, body: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _health(self) -> dict[str, object]:
        repo_health = self.repositories.health() if hasattr(self.repositories, "health") else {"backend": type(self.repositories).__name__}
        return {
            "status": "ok",
            "db_backend": getattr(self.repositories, "backend", type(self.repositories).__name__),
            "kafka_bootstrap": CLOUD_KAFKA_BOOTSTRAP,
            "topics": TOPICS,
            "repository": repo_health,
            "auth": {
                "read_token_configured": bool(self.read_token),
                "write_token_configured": bool(self.write_token),
                "admin_token_configured": bool(self.admin_token),
            },
        }

    def _audit(self, action: str, role: str, details: dict[str, object]) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "role": role,
            "client": self.client_address[0] if self.client_address else None,
            "details": details,
        }
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    def _render_page(self) -> str:
        summary = self.repositories.cloud_events.summary()
        events = self.repositories.cloud_events.latest_events(25)
        zones = self.repositories.twin_state.zones()
        feedback = self.repositories.feedback.latest(10)
        event_rows = "".join(
            "<tr>"
            f"<td>{html.escape(str(row.get('ingested_at', row.get('created_at', ''))))}</td>"
            f"<td>{html.escape(str(row.get('topic', '')))}</td>"
            f"<td>{html.escape(str(row.get('event_type', '')))}</td>"
            f"<td>{html.escape(str(row.get('sensor_id', '')))}</td>"
            f"<td>{html.escape(str(row.get('scenario', '')))}</td>"
            f"<td>{html.escape(str(row.get('result', '')))}</td>"
            "</tr>"
            for row in events
        )
        zone_rows = "".join(
            "<tr>"
            f"<td>{html.escape(str(row.get('zone_id', '')))}</td>"
            f"<td>{html.escape(str(row.get('last_sensor_id', '')))}</td>"
            f"<td>{html.escape(str(row.get('scenario', '')))}</td>"
            f"<td>{html.escape(str(row.get('severity', '')))}</td>"
            f"<td>{html.escape(str(row.get('decision', '')))}</td>"
            f"<td>{html.escape(str(row.get('updated_at', '')))}</td>"
            "</tr>"
            for row in zones
        )
        feedback_rows = "".join(
            "<tr>"
            f"<td>{html.escape(str(row.get('event_id', '')))}</td>"
            f"<td>{html.escape(str(row.get('zone_id', '')))}</td>"
            f"<td>{html.escape(str(row.get('target', '')))}</td>"
            f"<td>{html.escape(str(row.get('corrected_action', '')))}</td>"
            f"<td>{html.escape(str(row.get('reviewer_id', '')))}</td>"
            "</tr>"
            for row in feedback
        )
        backend = html.escape(str(getattr(self.repositories, "backend", "unknown")))
        return f"""
<!doctype html>
<title>Agentic Fog Cloud Dashboard</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 24px; color: #172033; }}
h1 {{ margin-bottom: 4px; }}
.cards {{ display: flex; gap: 12px; margin: 18px 0; flex-wrap: wrap; }}
.card {{ border: 1px solid #d8dee9; padding: 12px; min-width: 150px; }}
table {{ border-collapse: collapse; width: 100%; margin-bottom: 28px; }}
th, td {{ border: 1px solid #d8dee9; padding: 8px; text-align: left; font-size: 14px; }}
th {{ background: #f3f6fb; }}
code {{ background: #f3f6fb; padding: 2px 4px; }}
</style>
<h1>Agentic Fog Cloud Dashboard</h1>
<p>Dashboard backed by repository backend: <strong>{backend}</strong>.</p>
<div class="cards">
  <div class="card"><strong>Total events</strong><br>{summary.get('total_events', 0)}</div>
  <div class="card"><strong>Critical events</strong><br>{summary.get('critical_events', 0)}</div>
  <div class="card"><strong>Backend</strong><br><code>{backend}</code></div>
</div>
<h2>Digital Twin Zones</h2>
<table><tr><th>Zone</th><th>Sensor</th><th>Scenario</th><th>Severity</th><th>Decision</th><th>Updated</th></tr>{zone_rows}</table>
<h2>Latest Human Feedback Labels</h2>
<table><tr><th>Event</th><th>Zone</th><th>Label</th><th>Corrected Action</th><th>Reviewer</th></tr>{feedback_rows}</table>
<h2>Latest Cloud Events</h2>
<table><tr><th>Ingested</th><th>Topic</th><th>Type</th><th>Sensor</th><th>Scenario</th><th>Result</th></tr>{event_rows}</table>
<p>JSON APIs: <code>/api/health</code>, <code>/api/summary</code>, <code>/api/events</code>, <code>/api/twin</code>, <code>/api/feedback</code>, <code>/api/feedback/export</code>, <code>/api/optimize/irrigation</code></p>
"""


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_float(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.getenv("DASHBOARD_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("DASHBOARD_PORT", "8050")))
    parser.add_argument("--cloud-db", default=os.getenv("CLOUD_DB_PATH", "state/cloud_events.db"))
    parser.add_argument("--twin-db", default=os.getenv("DIGITAL_TWIN_DB_PATH", "state/digital_twin.db"))
    parser.add_argument("--feedback-path", default=os.getenv("FEEDBACK_STORE_PATH", "state/human_feedback.jsonl"))
    parser.add_argument("--feedback-export", default=os.getenv("FEEDBACK_EXPORT_PATH", "data/human_feedback_labels.jsonl"))
    parser.add_argument("--audit-path", default=os.getenv("DASHBOARD_AUDIT_PATH", "logs/dashboard_audit.jsonl"))
    parser.add_argument("--db-backend", default=os.getenv("DB_BACKEND", "sqlite"))
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    args = parser.parse_args()

    DashboardHandler.repositories = build_repositories(
        db_backend=args.db_backend,
        database_url=args.database_url,
        cloud_db=args.cloud_db,
        twin_db=args.twin_db,
        feedback_path=args.feedback_path,
    )
    legacy_token = os.getenv("DASHBOARD_TOKEN") or None
    DashboardHandler.read_token = os.getenv("DASHBOARD_READ_TOKEN") or legacy_token
    DashboardHandler.write_token = os.getenv("DASHBOARD_WRITE_TOKEN") or legacy_token
    DashboardHandler.admin_token = os.getenv("DASHBOARD_ADMIN_TOKEN") or legacy_token
    DashboardHandler.feedback_export_path = args.feedback_export
    DashboardHandler.audit_path = Path(args.audit_path)
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"dashboard running at http://{args.host}:{args.port}; backend={DashboardHandler.repositories.backend}")
    server.serve_forever()


if __name__ == "__main__":
    main()
