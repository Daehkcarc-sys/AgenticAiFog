"""FedAvg aggregator: weighted average of client model parameters."""

from __future__ import annotations

from typing import Any


def fedavg(
    client_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Weighted average of client weight dicts (FedAvg, McMahan et al. 2017).

    Parameters
    ----------
    client_results : list of dicts, each containing:
        params   — {"W": list[list[float]], "b": list[float]}
        n_train  — number of local training samples (used as weight)

    Returns
    -------
    Aggregated global params dict with keys "W" and "b".
    """
    if not client_results:
        raise ValueError("client_results must be non-empty")

    total_n = sum(r["n_train"] for r in client_results)
    if total_n == 0:
        raise ValueError("total training samples across clients is zero")

    # Use first client to determine shape
    ref_W = client_results[0]["params"]["W"]
    n_classes = len(ref_W)
    n_features = len(ref_W[0])
    n_b = len(client_results[0]["params"]["b"])

    agg_W = [[0.0] * n_features for _ in range(n_classes)]
    agg_b = [0.0] * n_b

    for result in client_results:
        w_i = result["n_train"] / total_n
        W = result["params"]["W"]
        b = result["params"]["b"]
        for k in range(n_classes):
            for j in range(n_features):
                agg_W[k][j] += w_i * W[k][j]
        for k in range(n_b):
            agg_b[k] += w_i * b[k]

    return {"W": agg_W, "b": agg_b}


def scaffold_correction(
    global_params: dict[str, Any],
    client_results: list[dict[str, Any]],
    lr_global: float = 1.0,
) -> dict[str, Any]:
    """Simplified SCAFFOLD-style global model update.

    Applies a weighted drift correction on top of FedAvg by computing the
    mean parameter delta and scaling it by ``lr_global``.  This is a
    heuristic variant, not the full SCAFFOLD algorithm with control variates.
    """
    base = fedavg(client_results)
    gW = global_params["W"]
    gb = global_params["b"]
    n_classes = len(base["W"])
    n_features = len(base["W"][0])
    corrected_W = [
        [gW[k][j] + lr_global * (base["W"][k][j] - gW[k][j]) for j in range(n_features)]
        for k in range(n_classes)
    ]
    corrected_b = [gb[k] + lr_global * (base["b"][k] - gb[k]) for k in range(len(gb))]
    return {"W": corrected_W, "b": corrected_b}
