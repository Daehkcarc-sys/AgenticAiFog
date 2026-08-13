"""Federated learning orchestrator: multi-round FedAvg over a prepared dataset.

Usage::

    python -m federated.fl_runner --data federated_output/synthetic --rounds 10
    python -m federated.fl_runner --data federated_output/synthetic --rounds 5 \\
        --clients 2 --lr 0.05 --output fl_results.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from federated.aggregator import fedavg
from federated.model import (
    MiniLogisticRegression,
    N_CLASSES,
    N_FEATURES,
    accuracy,
    load_jsonl,
    macro_f1,
)
from federated.trainer import train_local


def _discover_clients(data_dir: Path) -> list[Path]:
    """Return sorted list of per-client directories in data_dir."""
    clients = sorted(
        p for p in data_dir.iterdir()
        if p.is_dir() and (p / "train.jsonl").exists()
    )
    if not clients:
        raise FileNotFoundError(
            f"no client directories with train.jsonl found in {data_dir}"
        )
    return clients


def _evaluate_global(
    global_params: dict[str, Any],
    client_dirs: list[Path],
) -> dict[str, float]:
    """Evaluate the global model on all clients' test sets."""
    all_true: list[int] = []
    all_pred: list[int] = []
    model = MiniLogisticRegression()
    model.set_params(global_params)
    for client_dir in client_dirs:
        test_path = client_dir / "test.jsonl"
        if not test_path.exists():
            continue
        X, y = load_jsonl(test_path)
        if not X:
            continue
        preds = model.predict(X)
        all_true.extend(y)
        all_pred.extend(preds)
    if not all_true:
        return {"global_test_acc": 0.0, "global_test_macro_f1": 0.0}
    return {
        "global_test_acc": round(accuracy(all_true, all_pred), 4),
        "global_test_macro_f1": round(macro_f1(all_true, all_pred), 4),
    }


def run_federated_learning(
    data_dir: Path,
    rounds: int = 10,
    client_fraction: float = 1.0,
    epochs: int = 20,
    lr: float = 0.05,
    batch_size: int = 32,
    l2: float = 1e-4,
    seed: int = 0,
    verbose: bool = True,
) -> dict[str, Any]:
    """Run FedAvg over the prepared dataset directory.

    Parameters
    ----------
    data_dir         : directory produced by federated.dataset_builder
    rounds           : number of communication rounds
    client_fraction  : fraction of clients selected per round (1.0 = all)
    epochs, lr, batch_size, l2, seed : local training hyper-parameters
    verbose          : print per-round metrics

    Returns
    -------
    dict with keys:
      rounds_history   — per-round list of metrics
      final_params     — global model weights after last round
      global_test_acc  — accuracy on all test sets
      global_test_macro_f1
    """
    import random
    rng = random.Random(seed)

    all_clients = _discover_clients(data_dir)
    n_clients = max(1, int(len(all_clients) * client_fraction))

    # Initial global model (zero-initialised)
    global_model = MiniLogisticRegression(lr=lr, epochs=epochs, batch_size=batch_size, l2=l2, seed=seed)
    global_params = global_model.get_params()

    history: list[dict[str, Any]] = []

    for rnd in range(1, rounds + 1):
        selected = rng.sample(all_clients, n_clients)
        client_results = []
        for client_dir in selected:
            try:
                result = train_local(
                    client_dir,
                    global_params=global_params,
                    epochs=epochs,
                    lr=lr,
                    batch_size=batch_size,
                    l2=l2,
                    seed=seed + rnd,
                )
                client_results.append(result)
            except ValueError as exc:
                if verbose:
                    print(f"  [round {rnd}] skipping {client_dir.name}: {exc}")

        if not client_results:
            if verbose:
                print(f"  [round {rnd}] no valid clients — skipping aggregation")
            continue

        global_params = fedavg(client_results)

        round_metrics: dict[str, Any] = {
            "round": rnd,
            "clients_used": len(client_results),
            "mean_train_acc": round(
                sum(r["train_acc"] for r in client_results) / len(client_results), 4
            ),
        }
        val_accs = [r["val_acc"] for r in client_results if r["val_acc"] is not None]
        val_f1s = [r["val_macro_f1"] for r in client_results if r["val_macro_f1"] is not None]
        if val_accs:
            round_metrics["mean_val_acc"] = round(sum(val_accs) / len(val_accs), 4)
        if val_f1s:
            round_metrics["mean_val_macro_f1"] = round(sum(val_f1s) / len(val_f1s), 4)

        history.append(round_metrics)
        if verbose:
            print(
                f"  round {rnd:>3}/{rounds} | clients={len(client_results)} "
                f"| train_acc={round_metrics['mean_train_acc']:.4f}"
                + (f" | val_acc={round_metrics.get('mean_val_acc', 'N/A'):.4f}" if val_accs else "")
            )

    eval_metrics = _evaluate_global(global_params, all_clients)
    if verbose:
        print(f"\n  global test acc={eval_metrics['global_test_acc']:.4f} "
              f"macro-F1={eval_metrics['global_test_macro_f1']:.4f}")

    return {
        "rounds_history": history,
        "final_params": global_params,
        **eval_metrics,
        "n_rounds": rounds,
        "n_clients_total": len(all_clients),
        "client_fraction": client_fraction,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True,
                        help="Dataset directory (e.g. federated_output/synthetic)")
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--client-fraction", type=float, default=1.0)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--lr", type=float, default=0.05)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--l2", type=float, default=1e-4)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = run_federated_learning(
        data_dir=args.data,
        rounds=args.rounds,
        client_fraction=args.client_fraction,
        epochs=args.epochs,
        lr=args.lr,
        batch_size=args.batch_size,
        l2=args.l2,
        seed=args.seed,
        verbose=True,
    )
    # Don't print weights — too verbose
    printable = {k: v for k, v in result.items() if k != "final_params"}
    rendered = json.dumps(printable, indent=2)
    print("\n" + rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        # Save full result including weights
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
