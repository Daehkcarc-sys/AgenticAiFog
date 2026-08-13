"""Fog-side inference wrapper for the federated tomato yield prediction model.

Loads the global federated model produced by ``final_fog_yield_model1.zip``
and exposes a clean ``predict(features)`` API that the Fog pipeline can call
to estimate tomato yield (t/ha) from plot-level seasonal features.

The model is a 3-layer MLP (65 → 32 → 16 → 1) trained with FedAvg across
9 year-based Fog clients on the Carucci industrial-tomato dataset.
Performance (30-seed repeated evaluation): MAE ≈ 11.0 t/ha, R² ≈ 0.62.

Dependencies (optional — install requirements-yield.txt):
    pip install torch scikit-learn

Usage::

    from federated.yield_predictor import FogYieldPredictor, DEFAULT_MODEL_DIR
    predictor = FogYieldPredictor()                 # loads from default path
    result = predictor.predict(features_dict)
    print(result["predicted_yield"], result["unit"])  # e.g. 71.6 t/ha

Fog request / response contract::

    request  = {"zone_id": "year_2005", "timestamp": "...", "features": {...}}
    response = {"predicted_yield": 71.6, "unit": "t/ha",
                "source": "federated_global_yield_model", ...}
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_MODEL_DIR = Path(__file__).parent / "yield_model"

_MISSING_DEPS_MSG = (
    "Yield predictor requires torch and scikit-learn.\n"
    "Install: pip install -r requirements-yield.txt"
)


def _build_mlp(input_dim: int, hidden_dims: list[int], dropout: float):
    """Build the same MLP architecture used during federated training."""
    try:
        import torch.nn as nn
    except ImportError:
        raise ImportError(_MISSING_DEPS_MSG)

    layers: list[nn.Module] = []
    in_dim = input_dim
    for h in hidden_dims:
        layers += [
            nn.Linear(in_dim, h),
            nn.BatchNorm1d(h),
            nn.ReLU(),
            nn.Dropout(dropout),
        ]
        in_dim = h
    layers.append(nn.Linear(in_dim, 1))
    return nn.Sequential(*layers)


class FogYieldPredictor:
    """Loads the federated yield model and runs inference.

    Parameters
    ----------
    model_dir : directory containing the package files extracted from
                ``final_fog_yield_model1.zip``.
    device    : ``"cpu"`` or ``"cuda"`` — defaults to CPU.
    """

    def __init__(
        self,
        model_dir: Path | str = DEFAULT_MODEL_DIR,
        device: str = "cpu",
    ) -> None:
        self._dir = Path(model_dir)
        self._device = device
        self._model = None
        self._imputer = None
        self._scaler = None
        self._schema: dict[str, Any] = {}
        self._target_mean: float = 0.0
        self._target_std: float = 1.0
        self._load()

    # ── Public API ──────────────────────────────────────────────────────────

    def predict(self, features: dict[str, Any]) -> dict[str, Any]:
        """Predict tomato yield from a feature dict.

        Parameters
        ----------
        features : dict containing any subset of the 65 expected feature keys
                   (missing values are imputed automatically).

        Returns
        -------
        dict with keys: predicted_yield (float, t/ha), unit, confidence_note,
                        source, model_version.
        """
        try:
            import numpy as np
            import torch
        except ImportError:
            raise ImportError(_MISSING_DEPS_MSG)

        feature_names = self._schema["feature_names"]
        raw = np.array(
            [features.get(k, float("nan")) for k in feature_names],
            dtype=np.float32,
        ).reshape(1, -1)

        x = self._imputer.transform(raw)
        x = self._scaler.transform(x)
        tensor = torch.tensor(x, dtype=torch.float32).to(self._device)

        self._model.eval()
        with torch.no_grad():
            out = self._model(tensor).item()

        predicted_yield = round(out * self._target_std + self._target_mean, 4)
        return {
            "predicted_yield": predicted_yield,
            "unit": self._schema.get("target_unit", "t/ha"),
            "source": "federated_global_yield_model",
            "model_version": "FedAvg_v4",
            "confidence_note": (
                "mean MAE ≈ 11.0 t/ha over 30 seeds; "
                "year-based fog clients; no differential privacy"
            ),
        }

    def handle_fog_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Process a full fog request envelope (zone_id, timestamp, features).

        Mirrors the contract in ``fog_request_example.json``.
        """
        features = request.get("features") or {}
        result = self.predict(features)
        result["zone_id"] = request.get("zone_id")
        result["request_timestamp"] = request.get("timestamp")
        return result

    @property
    def feature_names(self) -> list[str]:
        return list(self._schema.get("feature_names", []))

    @property
    def model_card(self) -> dict[str, Any]:
        card_path = self._dir / "model_card.json"
        if card_path.exists():
            return json.loads(card_path.read_text(encoding="utf-8"))
        return {}

    # ── Private helpers ─────────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            import joblib
            import torch
        except ImportError:
            raise ImportError(_MISSING_DEPS_MSG)

        # Model config
        cfg = json.loads((self._dir / "model_config.json").read_text())
        self._model = _build_mlp(
            cfg["input_dim"], cfg["hidden_dims"], cfg["dropout"]
        ).to(self._device)
        state = torch.load(
            self._dir / "global_yield_model.pt",
            map_location=self._device,
            weights_only=True,
        )
        self._model.load_state_dict(state)

        # Preprocessors
        self._imputer = joblib.load(self._dir / "imputer.joblib")
        self._scaler = joblib.load(self._dir / "scaler.joblib")

        # Schema
        self._schema = json.loads(
            (self._dir / "preprocessor_schema.json").read_text(encoding="utf-8")
        )
        self._target_mean = float(self._schema.get("target_mean", 0.0))
        self._target_std = float(self._schema.get("target_std", 1.0))


def load_example_request() -> dict[str, Any]:
    """Return the example Fog request bundled with the model package."""
    path = DEFAULT_MODEL_DIR / "fog_request_example.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_example_response() -> dict[str, Any]:
    """Return the expected response for the example request."""
    path = DEFAULT_MODEL_DIR / "fog_response_example.json"
    return json.loads(path.read_text(encoding="utf-8"))
