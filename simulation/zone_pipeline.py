"""Zone-aware fog pipeline that wires ZoneContextManager into FogPipeline.

Satisfies items 1–5 in the main missing work list:

  1. TelemetryRecord → FogPipeline adapter (via fog_adapter.telemetry_to_pipeline_message)
  2. Zone time-window synchronisation across devices (ZoneContextManager)
  3. ZoneContext injected into Criticality and Decision Agents via message enrichment
  4. Link state and fault labels forwarded to the pipeline context
  5. NTN/offline link state activates local-only routing in DecisionAgent
"""

from __future__ import annotations

from typing import Any

from decision_cache import DecisionCache
from metrics import PipelineMetrics
from pipeline import FogPipeline
from context.zone_state import ZoneContextManager
from simulation.fog_adapter import telemetry_to_pipeline_message
from simulation.telemetry_schema import TelemetryRecord


class ZoneFogPipeline:
    """FogPipeline enriched with zone-level context, TelemetryRecord input,
    and optional digital twin synchronisation.

    For each arriving record:
    1. Zone window is updated with delivered sensor readings.
    2. Zone context snapshot (means, slopes, VPD, anomalies) is attached.
    3. If a DigitalTwinEngine is supplied, the twin is advanced via
       ``apply_fog_summary()`` after the fog decision is made.

    Usage::

        from digital_twin.simulator import DigitalTwinEngine
        twin = DigitalTwinEngine()
        zfp = ZoneFogPipeline(twin=twin)
        result = zfp.run(record)
        state = zfp.twin_dashboard()   # current twin state
    """

    def __init__(
        self,
        metrics: PipelineMetrics | None = None,
        cache: DecisionCache | None = None,
        max_zone_records: int = 256,
        twin: Any | None = None,
    ) -> None:
        self._pipeline = FogPipeline(metrics=metrics, cache=cache)
        self._zone_mgr = ZoneContextManager(max_records_per_zone=max_zone_records)
        self._twin = twin

    def run(self, record: TelemetryRecord) -> str:
        """Process a TelemetryRecord through the zone-aware fog pipeline."""
        try:
            self._zone_mgr.add(record)
        except ValueError:
            pass

        message = telemetry_to_pipeline_message(record)

        try:
            zone_ctx = self._zone_mgr.snapshot(record.zone_id)
            message["zone_context"] = zone_ctx.to_dict()
        except KeyError:
            pass

        result = self._pipeline.run(message)

        # Feed outcome back into the digital twin
        if self._twin is not None:
            try:
                self._twin.apply_fog_summary({
                    "sensor_id": record.device_id,
                    "zone_id": record.zone_id,
                    "raw_readings": {
                        k: float(v)
                        for k, v in record.readings.items()
                        if isinstance(v, (int, float))
                    },
                })
            except Exception:  # noqa: BLE001
                pass

        return result

    @property
    def cache_stats(self) -> dict | None:
        return self._pipeline.cache_stats

    def zone_snapshot(self, zone_id: str) -> dict | None:
        """Return the latest ZoneContext dict for a zone, or None."""
        try:
            return self._zone_mgr.snapshot(zone_id).to_dict()
        except KeyError:
            return None

    def twin_dashboard(self) -> dict[str, Any] | None:
        """Return the twin's dashboard state dict, or None if no twin attached."""
        if self._twin is None:
            return None
        return self._twin.dashboard_state()
