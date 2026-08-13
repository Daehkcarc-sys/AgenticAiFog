"""Local training step for one FL client (items 21-24)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from federated.model import (
    MiniLogisticRegression,
    accuracy,
    load_jsonl,
    macro_f1,
)


def train_local(
    client_dir: Path,
    global_params: dict[str, Any] | None = None,
    epochs: int = 20,
    lr: float = 0.05,
    batch_size: int = 32,
    l2: float = 1e-4,
    seed: int = 0,
) -> dict[str, Any]:
    """Train a local model for one client.

    Parameters
    ----------
    client_dir : directory containing train.jsonl / validation.jsonl / test.jsonl
    global_params : weight dict from the server (None = random init for round 0)
    epochs, lr, batch_size, l2, seed : training hyper-parameters

    Returns
    -------
    dict with keys:
      params        — updated weight dict ready for FedAvg
      n_train       — number of training samples
      train_acc     — training accuracy
      val_acc       — validation accuracy (or None)
      val_macro_f1  — validation macro-F1 (or None)
    """
    train_X, train_y = load_jsonl(client_dir / "train.jsonl")
    if not train_X:
        raise ValueError(f"no usable training samples in {client_dir}")

    model = MiniLogisticRegression(lr=lr, epochs=epochs, batch_size=batch_size, l2=l2, seed=seed)
    if global_params is not None:
        model.set_params(global_params)

    model.fit(train_X, train_y)
    train_pred = model.predict(train_X)
    train_acc = accuracy(train_y, train_pred)

    val_acc = val_f1 = None
    val_path = client_dir / "validation.jsonl"
    if val_path.exists():
        val_X, val_y = load_jsonl(val_path)
        if val_X:
            val_pred = model.predict(val_X)
            val_acc = accuracy(val_y, val_pred)
            val_f1 = macro_f1(val_y, val_pred)

    return {
        "params": model.get_params(),
        "n_train": len(train_X),
        "train_acc": round(train_acc, 4),
        "val_acc": round(val_acc, 4) if val_acc is not None else None,
        "val_macro_f1": round(val_f1, 4) if val_f1 is not None else None,
    }
