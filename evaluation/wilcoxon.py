"""Pure-Python paired Wilcoxon signed-rank test (item 19).

No external dependencies required (no scipy/statsmodels).  Uses a normal
approximation for the p-value, which is accurate for n >= 10.

Reference: Wilcoxon, F. (1945). Individual comparisons by ranking methods.
Biometrics Bulletin 1(6), 80–83.

Usage::

    from evaluation.wilcoxon import wilcoxon_signed_rank
    stat, p, effect = wilcoxon_signed_rank(b0_latencies, b5_latencies)
    print(f"W={stat}, p={p:.4f}, r={effect:.3f}")
"""

from __future__ import annotations

import math
from typing import Sequence


def wilcoxon_signed_rank(
    x: Sequence[float],
    y: Sequence[float],
) -> tuple[float, float, float]:
    """Paired Wilcoxon signed-rank test.

    Args:
        x: First sample (e.g. baseline B0 latencies across seeds).
        y: Second sample (e.g. baseline B5 latencies — same seeds, same order).

    Returns:
        (W, p_value, effect_size_r) where:
          W           — Wilcoxon test statistic (min of W+, W-)
          p_value     — two-tailed p-value via normal approximation
          effect_size — r = Z / sqrt(n), where n is the number of non-zero pairs

    Raises:
        ValueError if x and y have different lengths or fewer than 2 elements.
    """
    if len(x) != len(y):
        raise ValueError("x and y must have the same length")
    if len(x) < 2:
        raise ValueError("at least 2 paired observations are required")

    differences = [xi - yi for xi, yi in zip(x, y) if xi != yi]

    if not differences:
        return 0.0, 1.0, 0.0

    abs_diffs = [abs(d) for d in differences]

    # Rank |d_i| with average-rank tie handling
    sorted_abs = sorted(enumerate(abs_diffs), key=lambda t: t[1])
    ranks = [0.0] * len(abs_diffs)
    i = 0
    while i < len(sorted_abs):
        j = i
        while j < len(sorted_abs) - 1 and sorted_abs[j + 1][1] == sorted_abs[i][1]:
            j += 1
        avg_rank = (i + 1 + j + 1) / 2.0
        for k in range(i, j + 1):
            ranks[sorted_abs[k][0]] = avg_rank
        i = j + 1

    w_plus = sum(r for d, r in zip(differences, ranks) if d > 0)
    w_minus = sum(r for d, r in zip(differences, ranks) if d < 0)
    w_stat = min(w_plus, w_minus)

    n = len(differences)
    mean_w = n * (n + 1) / 4.0
    std_w = math.sqrt(n * (n + 1) * (2 * n + 1) / 24.0)

    if std_w == 0:
        p_value = 1.0
        z = 0.0
    else:
        # Continuity correction
        z = (w_stat - mean_w + 0.5) / std_w
        p_value = 2.0 * _normal_cdf(z)

    effect_size = abs(z) / math.sqrt(n)
    return round(w_stat, 4), round(p_value, 6), round(effect_size, 4)


def _normal_cdf(z: float) -> float:
    """Standard normal CDF via complementary error function."""
    return 0.5 * math.erfc(-z / math.sqrt(2))
