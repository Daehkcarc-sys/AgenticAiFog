"""Zone-aware fog pipeline that wires ZoneContextManager into FogPipeline.

Satisfies items 1–5 in the main missing work list:

  1. TelemetryRecord → FogPipeline adapter (via fog_adapter.telemetry_to_pipeline_message)
  2. Zone time-window synchronisation across devices (ZoneContextManager)
  3. ZoneContext injected into Criticality and Decision Agents via message enrichment
  4. Link state and fault labels forwarded to the pipeline context
  5. NTN/offline link state activates local-only routing in DecisionAgent
"""

from __future__ import annotations

from decision_cache import DecisionCache
from metrics import PipelineMetrics
from pipeline import FogPipeline
from context.zone_state import ZoneContextManager
from simulation.fog_adapter import telemetry_to_pipeline_message
from simulation.telemetry_schema import TelemetryRecord


class ZoneFogPipeline:
    """FogPipeline enriched with zone-level context and TelemetryRecord input.

    Maintains one ZoneContextManager across all zones. For each arriving record
    the manager is updated and a ZoneContext snapshot is attached to the
    pipeline message so agents downstream (CriticalityAgent, DecisionAgent) can
    incorporate zone-level trends and cross-sensor anomalies.

    Usage::

        zfp = ZoneFogPipeline()
        result = zfp.run(record)   # record is a TelemetryRecord
    """

    def __init__(
        self,
        metrics: PipelineMetrics | None = None,
        cache: DecisionCache | None = None,
        max_zone_records: int = 256,
    ) -> None:
        self._pipeline = FogPipeline(metrics=metrics, cache=cache)
        self._zone_mgr = ZoneContextManager(max_records_per_zone=max_zone_records)

    def run(self, record: TelemetryRecord) -> str:
        """Process a TelemetryRecord through the zone-aware fog pipeline."""
        # Update zone window with this delivered record.
        # Out-of-order records are silently skipped to keep the manager stable.
        try:
            self._zone_mgr.add(record)
        except ValueError:
            pass

        message = telemetry_to_pipeline_message(record)

        # Attach zone context snapshot when records are available (item 3).
        try:
            zone_ctx = self._zone_mgr.snapshot(record.zone_id)
            message["zone_context"] = zone_ctx.to_dict()
        except KeyError:
            pass

        return self._pipeline.run(message)

    @property
    def cache_stats(self) -> dict | None:
        return self._pipeline.cache_stats

    def zone_snapshot(self, zone_id: str) -> dict | None:
        """Return the latest ZoneContext dict for a zone, or None."""
        try:
            return self._zone_mgr.snapshot(zone_id).to_dict()
        except KeyError:
            return None
