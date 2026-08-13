"""Multi-seed statistical evaluation of baseline comparisons (items 17–20).

Runs all specified baselines over a range of seeds, aggregates per-metric
results, and applies the paired Wilcoxon signed-rank test between each
baseline pair.

Usage::

    python -m evaluation.statistical_eval --seeds 30 --output stats.json
    python -m evaluation.statistical_eval --seeds 10 --baselines B0 B5
    python -m evaluation.statistical_eval --seeds 5 --compare B0,B5 B2,B5
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from evaluation.wilcoxon import wilcoxon_signed_rank
from simulation.baselines import Baseline
from simulation.experiment_runner import run_experiment

_METRICS = [
    "decision_coverage",
    "mean_latency_ms",
    "bytes_to_cloud",
    "communication_cost",
    "energy_units",
    "macro_f1_observed_abnormal",
    "false_alarm_rate",
]


def _ci_95(values: list[float]) -> tuple[float, float]:
    """95% confidence interval via t-distribution approximation."""
    n = len(values)
    if n < 2:
        m = values[0] if values else 0.0
        return round(m, 4), round(m, 4)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    se = (variance / n) ** 0.5
    # t-critical ≈ 2.0 for n>=10, conservative 2.262 for n=10
    t = 2.262 if n <= 10 else 2.0
    margin = t * se
    return round(mean - margin, 4), round(mean + margin, 4)


def collect_results(
    baselines: list[Baseline],
    seeds: list[int],
    duration_minutes: int = 120,
    sample_interval_minutes: int = 10,
) -> dict[str, list[dict[str, Any]]]:
    """Run each baseline for every seed; return {baseline_name: [run_dict, ...]}."""
    results: dict[str, list[dict[str, Any]]] = {b.value: [] for b in baselines}
    total = len(baselines) * len(seeds)
    done = 0
    for seed in seeds:
        for baseline in baselines:
            summary = run_experiment(baseline, seed, duration_minutes, sample_interval_minutes)
            results[baseline.value].append(summary)
            done += 1
            print(f"  [{done}/{total}] {baseline.value} seed={seed} "
                  f"coverage={summary.get('decision_coverage', 0):.2%} "
                  f"latency={summary.get('mean_latency_ms', 'N/A')} ms")
    return results


def aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute mean, std, and 95-CI for each metric across runs."""
    out: dict[str, Any] = {"n_runs": len(runs)}
    for metric in _METRICS:
        values = [r[metric] for r in runs if r.get(metric) is not None]
        if not values:
            continue
        mean = sum(values) / len(values)
        std = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))
        lo, hi = _ci_95(values)
        out[metric] = {
            "mean": round(mean, 4),
            "std": round(std, 4),
            "ci95_lo": lo,
            "ci95_hi": hi,
        }
    return out


def pairwise_tests(
    results: dict[str, list[dict[str, Any]]],
    pairs: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Run paired Wilcoxon tests for each metric across all requested pairs."""
    baseline_names = list(results)
    if pairs is None:
        # Compare every baseline against every other
        pairs = [
            (a, b)
            for i, a in enumerate(baseline_names)
            for b in baseline_names[i + 1:]
        ]
    tests: dict[str, Any] = {}
    for a_name, b_name in pairs:
        if a_name not in results or b_name not in results:
            continue
        a_runs = results[a_name]
        b_runs = results[b_name]
        n = min(len(a_runs), len(b_runs))
        if n < 2:
            continue
        key = f"{a_name}_vs_{b_name}"
        tests[key] = {}
        for metric in _METRICS:
            a_vals = [r[metric] for r in a_runs[:n] if r.get(metric) is not None]
            b_vals = [r[metric] for r in b_runs[:n] if r.get(metric) is not None]
            if len(a_vals) < 2 or len(a_vals) != len(b_vals):
                continue
            w, p, r = wilcoxon_signed_rank(a_vals, b_vals)
            tests[key][metric] = {
                "W": w,
                "p_value": p,
                "effect_size_r": r,
                "significant_05": p < 0.05,
            }
    return tests


def run_evaluation(
    baselines: list[Baseline],
    seeds: list[int],
    compare_pairs: list[tuple[str, str]] | None = None,
    duration_minutes: int = 120,
    sample_interval_minutes: int = 10,
) -> dict[str, Any]:
    print(f"Running {len(baselines)} baselines × {len(seeds)} seeds "
          f"= {len(baselines) * len(seeds)} experiments...")
    results = collect_results(baselines, seeds, duration_minutes, sample_interval_minutes)

    aggregated = {name: aggregate(runs) for name, runs in results.items()}

    pairs = None
    if compare_pairs:
        pairs = [(a, b) for a, b in compare_pairs]

    tests = pairwise_tests(results, pairs)

    return {
        "seeds": seeds,
        "n_seeds": len(seeds),
        "aggregated": aggregated,
        "wilcoxon_tests": tests,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seeds",
        type=int,
        default=10,
        help="Number of seeds to use (seeds will be 1, 2, ..., N)",
    )
    parser.add_argument(
        "--baselines",
        nargs="+",
        choices=["B0", "B1", "B2", "B3", "B4", "B5"],
        default=["B0", "B1", "B2", "B3", "B4", "B5"],
        help="Which baselines to evaluate",
    )
    parser.add_argument(
        "--compare",
        nargs="+",
        metavar="A,B",
        default=None,
        help="Explicit pairs for Wilcoxon test (e.g. B0,B5 B2,B5)",
    )
    parser.add_argument("--duration-minutes", type=int, default=120)
    parser.add_argument("--sample-interval-minutes", type=int, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    seeds = list(range(1, args.seeds + 1))
    baselines = [Baseline(b) for b in args.baselines]

    compare_pairs = None
    if args.compare:
        compare_pairs = []
        for pair_str in args.compare:
            parts = pair_str.split(",")
            if len(parts) == 2:
                compare_pairs.append((parts[0].strip(), parts[1].strip()))

    result = run_evaluation(
        baselines,
        seeds,
        compare_pairs=compare_pairs,
        duration_minutes=args.duration_minutes,
        sample_interval_minutes=args.sample_interval_minutes,
    )

    rendered = json.dumps(result, indent=2)
    print("\n" + rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
