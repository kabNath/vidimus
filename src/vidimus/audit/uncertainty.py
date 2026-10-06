"""Calibrated uncertainty: bootstrap CI + inter-judge agreement.

Why this module exists: every other LLM observability tool publishes
"hallucination rate: 3.2%" with no indication of statistical reliability.
That number could be 0.5% or 8% on the next batch — you have no way to
know. And if it came from a single LLM judge, the judge itself is biased
in ways the literature has documented extensively (Zheng et al. 2023,
Panickssery et al. 2024).

Vidimus refuses to publish point estimates. Every metric carries:

  - A 95% bootstrap confidence interval (non-parametric, distribution-free).
  - For LLM-as-judge metrics, an agreement coefficient between judges
    (Cohen's κ for 2 raters, Fleiss's κ for 3+, Krippendorff's α for
    ordinal/continuous outputs).

If judge agreement is poor (< 0.4), the attestation flags the metric as
low-confidence regardless of how tight the bootstrap CI looks.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class BootstrapCI:
    """Result of a bootstrap confidence interval computation."""

    point_estimate: float
    ci_low: float
    ci_high: float
    n: int
    iterations: int


def bootstrap_ci(
    samples: list[float],
    statistic: Callable[[np.ndarray], float] = np.mean,
    iterations: int = 1000,
    confidence: float = 0.95,
    seed: int | None = None,
) -> BootstrapCI:
    """Compute a non-parametric bootstrap confidence interval.

    Args:
        samples: Individual sample values. For a rate metric like
            hallucination_rate, this would be a list of 0/1 indicators.
        statistic: Function mapping an array of resampled values to a
            scalar. Default is the mean (correct for rates and averages).
        iterations: Number of bootstrap resamples. Default 1000 is the
            literature standard; 10000 is used for high-stakes reporting.
        confidence: Confidence level in (0, 1). Default 0.95.
        seed: Optional RNG seed for reproducibility.

    Returns:
        A BootstrapCI dataclass.
    """
    if not samples:
        raise ValueError("bootstrap_ci requires at least one sample")
    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")

    arr = np.asarray(samples, dtype=np.float64)
    n = len(arr)
    point = float(statistic(arr))

    rng = np.random.default_rng(seed)
    # Vectorized resampling: shape (iterations, n).
    indices = rng.integers(0, n, size=(iterations, n))
    resamples = arr[indices]
    stats = np.apply_along_axis(statistic, axis=1, arr=resamples)

    alpha = 1.0 - confidence
    ci_low = float(np.quantile(stats, alpha / 2))
    ci_high = float(np.quantile(stats, 1 - alpha / 2))

    return BootstrapCI(
        point_estimate=point,
        ci_low=ci_low,
        ci_high=ci_high,
        n=n,
        iterations=iterations,
    )


# --- Inter-rater agreement ---------------------------------------------


def cohens_kappa(rater_a: list[int], rater_b: list[int]) -> float:
    """Cohen's κ for two raters on the same N items, with categorical labels.

    Returns a value in [-1, 1]. 1 = perfect agreement, 0 = chance, < 0 worse than chance.

    Reference: Cohen (1960). "A coefficient of agreement for nominal scales."
    """
    if len(rater_a) != len(rater_b):
        raise ValueError(f"raters disagree on item count: {len(rater_a)} vs {len(rater_b)}")
    if not rater_a:
        raise ValueError("cannot compute kappa on empty input")

    n = len(rater_a)
    categories = sorted(set(rater_a) | set(rater_b))

    # Observed agreement.
    p_o = sum(1 for a, b in zip(rater_a, rater_b, strict=True) if a == b) / n

    # Expected agreement by chance.
    a_counts = Counter(rater_a)
    b_counts = Counter(rater_b)
    p_e = sum((a_counts[c] / n) * (b_counts[c] / n) for c in categories)

    if abs(1 - p_e) < 1e-12:
        # Both raters always pick the same label; agreement is by definition perfect.
        return 1.0
    return (p_o - p_e) / (1 - p_e)


def fleiss_kappa(ratings: list[list[int]]) -> float:
    """Fleiss's κ for k ≥ 3 raters on the same N items, with categorical labels.

    Args:
        ratings: A list of length N (items), where each element is a list
            of length k (raters) giving each rater's categorical label.

    Returns:
        κ in (-∞, 1]; values < 0 are pathological.

    Reference: Fleiss (1971). "Measuring nominal scale agreement among
    many raters."
    """
    if not ratings:
        raise ValueError("fleiss_kappa requires at least one item")
    n_items = len(ratings)
    n_raters = len(ratings[0])
    if n_raters < 2:
        raise ValueError(f"need at least 2 raters, got {n_raters}")
    if any(len(r) != n_raters for r in ratings):
        raise ValueError("all items must have the same number of raters")

    categories = sorted({lab for item in ratings for lab in item})

    # n_ij = number of raters who assigned item i to category j.
    n_ij = np.zeros((n_items, len(categories)), dtype=np.int64)
    for i, item in enumerate(ratings):
        cat_counts = Counter(item)
        for j, c in enumerate(categories):
            n_ij[i, j] = cat_counts.get(c, 0)

    # Per-item agreement.
    p_i = (n_ij**2).sum(axis=1) - n_raters
    p_i = p_i / (n_raters * (n_raters - 1))
    p_bar = p_i.mean()

    # Per-category marginals.
    p_j = n_ij.sum(axis=0) / (n_items * n_raters)
    p_e = (p_j**2).sum()

    if abs(1 - p_e) < 1e-12:
        return 1.0
    return float((p_bar - p_e) / (1 - p_e))


def krippendorff_alpha(
    ratings: list[list[float | None]],
    level: str = "nominal",
) -> float:
    """Krippendorff's α for any number of raters, missing values, and measurement levels.

    Args:
        ratings: A list of length N (items), each containing each rater's
            value (or None for missing). All items must have the same
            number of rater columns.
        level: "nominal", "ordinal", or "interval". Default "nominal".

    Returns:
        α in (-∞, 1]; 1 = perfect, 0 = chance, < 0 worse than chance.

    This is an implementation of the standard formulation suitable for
    small datasets. For very large datasets, a future version will use the
    coincidence-matrix approach for efficiency.

    Reference: Krippendorff (2011). "Computing Krippendorff's alpha-reliability."
    """
    if level not in ("nominal", "ordinal", "interval"):
        raise ValueError(f"unknown level: {level}")

    # Flatten into a list of (rater_col, item_idx, value) tuples ignoring None.
    if not ratings:
        raise ValueError("krippendorff_alpha requires at least one item")
    n_raters = len(ratings[0])
    if any(len(r) != n_raters for r in ratings):
        raise ValueError("all items must have the same number of rater columns")

    # Build pairs of values that came from the same item.
    pair_diffs: list[float] = []
    for item in ratings:
        present = [v for v in item if v is not None]
        if len(present) < 2:
            continue
        for i in range(len(present)):
            for j in range(i + 1, len(present)):
                pair_diffs.append(_distance(present[i], present[j], level))
    if not pair_diffs:
        return 1.0

    # All pairs across items for expected disagreement.
    all_values: list[float] = [v for item in ratings for v in item if v is not None]
    expected_diffs: list[float] = []
    for i in range(len(all_values)):
        for j in range(i + 1, len(all_values)):
            expected_diffs.append(_distance(all_values[i], all_values[j], level))

    if not expected_diffs:
        return 1.0

    observed = float(np.mean(pair_diffs))
    expected = float(np.mean(expected_diffs))
    if abs(expected) < 1e-12:
        return 1.0
    return 1.0 - observed / expected


def _distance(a: float, b: float, level: str) -> float:
    if level == "nominal":
        return 0.0 if a == b else 1.0
    if level == "interval":
        return (a - b) ** 2
    # ordinal: distance metric on ranks; for simplicity we use squared diff,
    # which behaves like interval. A full ordinal implementation would
    # require the rank distribution. Acceptable approximation for v0.1.
    return (a - b) ** 2
