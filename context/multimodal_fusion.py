"""Multimodal fusion placeholder for drone/satellite observations.

This module intentionally does not run image ML. It accepts compact metadata or
precomputed visual features from a future drone/satellite pipeline and converts
them into a deterministic fog-friendly context block.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class MultimodalFusionResult:
    """Normalized visual/remote-sensing context for the fog decision loop."""

    available: bool
    sources: list[str]
    features: dict[str, float]
    risk_indicators: list[str]
    semantic_summary: str
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MultimodalFusionAgent:
    """Fuse precomputed visual features with the sensor context contract.

    Expected input examples:

    ```python
    {
        "source": "drone",
        "ndvi": 0.42,
        "canopy_temperature": 36.5,
        "thermal_anomaly": 0.8,
        "disease_hotspot_score": 0.7,
    }
    ```

    A list of such dictionaries is also accepted. The output is deliberately
    small so Limon/cloud and Sonic/Sarra/ML can replace the producer later
    without changing the fog pipeline shape.
    """

    _NUMERIC_FEATURES = {
        "ndvi",
        "evi",
        "canopy_temperature",
        "thermal_anomaly",
        "water_stress_index",
        "disease_hotspot_score",
        "pest_hotspot_score",
        "soil_exposure_index",
    }

    def run(self, payload: Any) -> MultimodalFusionResult:
        observations = self._normalize(payload)
        if not observations:
            return MultimodalFusionResult(
                available=False,
                sources=[],
                features={},
                risk_indicators=[],
                semantic_summary="no multimodal observations supplied",
                limitations=[
                    "placeholder accepts metadata/precomputed features only",
                    "no drone/satellite image model is implemented yet",
                ],
            )

        sources = sorted(
            {
                str(obs.get("source") or obs.get("sensor_type") or "unknown_visual")
                for obs in observations
            }
        )
        features = self._average_features(observations)
        risk_indicators = self._risk_indicators(features)
        summary = self._semantic_summary(sources, risk_indicators)
        return MultimodalFusionResult(
            available=True,
            sources=sources,
            features=features,
            risk_indicators=risk_indicators,
            semantic_summary=summary,
            limitations=[
                "metadata/precomputed feature fusion only",
                "image ingestion and visual ML remain future integration work",
            ],
        )

    @staticmethod
    def _normalize(payload: Any) -> list[dict[str, Any]]:
        if payload is None:
            return []
        if isinstance(payload, dict):
            if isinstance(payload.get("observations"), list):
                return [obs for obs in payload["observations"] if isinstance(obs, dict)]
            return [payload]
        if isinstance(payload, list):
            return [obs for obs in payload if isinstance(obs, dict)]
        return []

    def _average_features(self, observations: list[dict[str, Any]]) -> dict[str, float]:
        grouped: dict[str, list[float]] = {}
        for observation in observations:
            for key in self._NUMERIC_FEATURES:
                value = observation.get(key)
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                grouped.setdefault(key, []).append(float(value))
        return {
            key: round(sum(values) / len(values), 3)
            for key, values in sorted(grouped.items())
            if values
        }

    @staticmethod
    def _risk_indicators(features: dict[str, float]) -> list[str]:
        indicators: list[str] = []
        ndvi = features.get("ndvi")
        canopy_temperature = features.get("canopy_temperature")
        thermal_anomaly = features.get("thermal_anomaly")
        water_stress = features.get("water_stress_index")
        disease_hotspot = features.get("disease_hotspot_score")
        pest_hotspot = features.get("pest_hotspot_score")
        soil_exposure = features.get("soil_exposure_index")

        if ndvi is not None and ndvi < 0.35:
            indicators.append("low vegetation index")
        if canopy_temperature is not None and canopy_temperature >= 35:
            indicators.append("high canopy temperature")
        if thermal_anomaly is not None and thermal_anomaly >= 0.7:
            indicators.append("thermal anomaly")
        if water_stress is not None and water_stress >= 0.7:
            indicators.append("visual water stress")
        if disease_hotspot is not None and disease_hotspot >= 0.65:
            indicators.append("possible disease hotspot")
        if pest_hotspot is not None and pest_hotspot >= 0.65:
            indicators.append("possible pest hotspot")
        if soil_exposure is not None and soil_exposure >= 0.7:
            indicators.append("high exposed soil")
        return indicators

    @staticmethod
    def _semantic_summary(sources: list[str], risk_indicators: list[str]) -> str:
        source_text = ", ".join(sources) if sources else "unknown visual source"
        if risk_indicators:
            return f"multimodal sources ({source_text}) indicate: {', '.join(risk_indicators)}"
        return f"multimodal sources ({source_text}) show no visual risk indicators"
