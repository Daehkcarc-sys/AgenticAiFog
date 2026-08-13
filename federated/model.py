"""Pure-Python multi-class logistic regression for federated learning.

No external ML library required. Uses mini-batch SGD with cross-entropy loss
and softmax output — compatible with FedAvg weight averaging.

Feature vector: fixed 8-dim numerical readings extracted from JSONL rows.
Classes: the 8 CriticalityScenario labels encoded as integers 0-7.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


# Fixed feature order shared across all clients so weight vectors are aligned.
FEATURE_KEYS = [
    "temperature",
    "humidity",
    "soil_moisture",
    "ph",
    "salinity",
    "pest_pressure",
    "rainfall",
    "irrigation_flow",
]

LABEL_ORDER = [
    "Normal",
    "Water deficit",
    "Flooding",
    "Heat stress",
    "Disease risk",
    "Pest infestation",
    "Soil degradation",
    "Equipment failure",
]
N_CLASSES = len(LABEL_ORDER)
N_FEATURES = len(FEATURE_KEYS)

_LABEL_TO_INT = {label: i for i, label in enumerate(LABEL_ORDER)}


def _softmax(logits: list[float]) -> list[float]:
    m = max(logits)
    exps = [math.exp(x - m) for x in logits]
    total = sum(exps)
    return [e / total for e in exps]


def _cross_entropy(probs: list[float], true_class: int) -> float:
    p = max(probs[true_class], 1e-15)
    return -math.log(p)


class MiniLogisticRegression:
    """Multi-class logistic regression with SGD.

    Parameters
    ----------
    lr : learning rate
    epochs : full passes over training data
    batch_size : mini-batch size (1 = pure SGD)
    l2 : L2 regularisation coefficient
    seed : PRNG seed for weight initialisation and shuffling
    """

    def __init__(
        self,
        lr: float = 0.05,
        epochs: int = 20,
        batch_size: int = 32,
        l2: float = 1e-4,
        seed: int = 0,
    ) -> None:
        self.lr = lr
        self.epochs = epochs
        self.batch_size = batch_size
        self.l2 = l2
        self._seed = seed
        # W[k][j] = weight for class k, feature j
        self.W: list[list[float]] = [
            [0.0] * N_FEATURES for _ in range(N_CLASSES)
        ]
        self.b: list[float] = [0.0] * N_CLASSES

    # ── Public API ──────────────────────────────────────────────────────────

    def fit(self, X: list[list[float]], y: list[int]) -> "MiniLogisticRegression":
        """Train on (X, y) in place; return self."""
        if len(X) != len(y) or not X:
            raise ValueError("X and y must be non-empty and the same length")
        import random
        rng = random.Random(self._seed)
        pairs = list(zip(X, y))
        for _ in range(self.epochs):
            rng.shuffle(pairs)
            for start in range(0, len(pairs), self.batch_size):
                batch = pairs[start: start + self.batch_size]
                self._update(batch)
        return self

    def predict(self, X: list[list[float]]) -> list[int]:
        return [self._predict_one(x) for x in X]

    def predict_proba(self, X: list[list[float]]) -> list[list[float]]:
        return [_softmax(self._logits(x)) for x in X]

    def get_params(self) -> dict[str, Any]:
        return {"W": [row[:] for row in self.W], "b": self.b[:]}

    def set_params(self, params: dict[str, Any]) -> None:
        self.W = [row[:] for row in params["W"]]
        self.b = params["b"][:]

    # ── Internal helpers ────────────────────────────────────────────────────

    def _logits(self, x: list[float]) -> list[float]:
        return [
            sum(self.W[k][j] * x[j] for j in range(N_FEATURES)) + self.b[k]
            for k in range(N_CLASSES)
        ]

    def _predict_one(self, x: list[float]) -> int:
        logits = self._logits(x)
        return logits.index(max(logits))

    def _update(self, batch: list[tuple[list[float], int]]) -> None:
        n = len(batch)
        # Accumulate gradients
        dW = [[0.0] * N_FEATURES for _ in range(N_CLASSES)]
        db = [0.0] * N_CLASSES
        for x, true_cls in batch:
            probs = _softmax(self._logits(x))
            for k in range(N_CLASSES):
                delta = probs[k] - (1.0 if k == true_cls else 0.0)
                for j in range(N_FEATURES):
                    dW[k][j] += delta * x[j]
                db[k] += delta
        # SGD step with L2 regularisation
        for k in range(N_CLASSES):
            for j in range(N_FEATURES):
                self.W[k][j] -= self.lr * (dW[k][j] / n + self.l2 * self.W[k][j])
            self.b[k] -= self.lr * db[k] / n


# ── Feature / label extraction from JSONL rows ──────────────────────────────

def row_to_xy(row: dict[str, Any]) -> tuple[list[float], int] | None:
    """Extract (feature_vector, label_int) from a JSONL row.

    Returns None for rows with no usable features or unknown labels.
    """
    features = row.get("features") or {}
    x = [float(features.get(k, 0.0) or 0.0) for k in FEATURE_KEYS]
    target = str(row.get("target", ""))
    label = _LABEL_TO_INT.get(target)
    if label is None:
        return None
    return x, label


def load_jsonl(path: Path) -> tuple[list[list[float]], list[int]]:
    """Load a split .jsonl file into (X, y) lists."""
    X, y = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        result = row_to_xy(row)
        if result is not None:
            xi, yi = result
            X.append(xi)
            y.append(yi)
    return X, y


def accuracy(y_true: list[int], y_pred: list[int]) -> float:
    if not y_true:
        return 0.0
    return sum(a == b for a, b in zip(y_true, y_pred)) / len(y_true)


def macro_f1(y_true: list[int], y_pred: list[int], n_classes: int = N_CLASSES) -> float:
    f1s = []
    for cls in range(n_classes):
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == cls and p == cls)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != cls and p == cls)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == cls and p != cls)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        f1s.append(f1)
    return sum(f1s) / n_classes if f1s else 0.0
