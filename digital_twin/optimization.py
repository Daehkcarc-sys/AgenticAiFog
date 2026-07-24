"""Optimization foundations for cloud-side digital twin services."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class OptimizationRecommendation:
    zone_id: str
    action: str
    priority: float
    reason: str
    expected_effect: dict[str, Any] = field(default_factory=dict)


class IrrigationOptimizer:
    """Simple deterministic optimizer for multi-zone irrigation scheduling.

    This is an architecture foundation, not a calibrated operations research model.
    It can later be replaced by linear programming, MPC, or an ML optimizer while
    preserving the same recommendation contract.
    """

    def recommend(
        self,
        zones: list[dict[str, Any]],
        water_budget_liters: float | None = None,
        forecast: dict[str, float] | None = None,
    ) -> list[OptimizationRecommendation]:
        forecast = forecast or {}
        rain_expected = float(forecast.get("rainfall", 0.0)) > 5.0
        recommendations: list[OptimizationRecommendation] = []
        for zone in zones:
            zone_id = str(zone.get("zone_id", "default-zone"))
            soil = zone.get("soil") if isinstance(zone.get("soil"), dict) else {}
            moisture = _number(soil.get("moisture"), default=_number(zone.get("soil_moisture"), 45.0))
            risk = _number(zone.get("risk_index"), 0.0)
            scenario = str(zone.get("last_scenario") or zone.get("scenario") or "")
            priority = max(risk, max(0.0, (35.0 - moisture) / 35.0))
            if rain_expected:
                action = "monitor"
                reason = "rain forecast reduces immediate irrigation priority"
                priority *= 0.5
            elif moisture < 25 or scenario == "Water deficit":
                action = "irrigate"
                reason = "low moisture or water deficit scenario"
            elif moisture > 80 or scenario == "Flooding":
                action = "stop_irrigation"
                reason = "high moisture or flooding scenario"
                priority = max(priority, 0.8)
            else:
                action = "monitor"
                reason = "zone is within operating moisture band"
            if water_budget_liters is not None and water_budget_liters <= 0 and action == "irrigate":
                action = "manual_review"
                reason = "irrigation needed but water budget is exhausted"
            recommendations.append(
                OptimizationRecommendation(
                    zone_id=zone_id,
                    action=action,
                    priority=round(min(1.0, priority), 3),
                    reason=reason,
                    expected_effect={"moisture_target": 45 if action == "irrigate" else moisture},
                )
            )
        return sorted(recommendations, key=lambda item: item.priority, reverse=True)


def _number(value: Any, default: float) -> float:
    return float(value) if isinstance(value, (int, float)) else default
