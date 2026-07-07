from __future__ import annotations

from typing import Iterable

from config import SENSOR_REGISTRY


class SensorRegistry:

    @classmethod
    def is_registered(cls, sensor_id: str) -> bool:
        if not isinstance(sensor_id, str):
            return False

        return sensor_id.upper() in {s.upper() for s in SENSOR_REGISTRY}


def validate_sensor_identity(sensor_id: str) -> bool:
    return SensorRegistry.is_registered(sensor_id)
