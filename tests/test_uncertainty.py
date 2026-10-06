"""Tests for bootstrap CI and inter-judge agreement."""

from __future__ import annotations

import numpy as np
import pytest

from vidimus.audit.uncertainty import (
    bootstrap_ci,
    cohens_kappa,
    fleiss_kappa,
    krippendorff_alpha,
)


class TestBootstrap:
    def test_constant_samples_yield_zero_width_ci(self) -> None:
        result = bootstrap_ci([0.5] * 100, seed=42)
        assert result.ci_low == pytest.approx(0.5, abs=1e-9)
        assert result.ci_high == pytest.approx(0.5, abs=1e-9)
        assert result.point_estimate == pytest.approx(0.5, abs=1e-9)

    def test_ci_contains_true_mean(self) -> None:
        rng = np.random.default_rng(0)
        samples = rng.binomial(1, 0.3, size=1000).astype(float).tolist()
        result = bootstrap_ci(samples, seed=1)
        # True mean is 0.3; CI should contain it.
        assert result.ci_low <= 0.3 <= result.ci_high

    def test_seed_reproducibility(self) -> None:
        samples = [0.0, 1.0] * 50
        r1 = bootstrap_ci(samples, seed=123)
        r2 = bootstrap_ci(samples, seed=123)
        assert r1.ci_low == r2.ci_low
        assert r1.ci_high == r2.ci_high

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            bootstrap_ci([])

    def test_invalid_confidence_raises(self) -> None:
        with pytest.raises(ValueError):
            bootstrap_ci([1.0], confidence=1.5)
        with pytest.raises(ValueError):
            bootstrap_ci([1.0], confidence=0.0)


class TestCohensKappa:
    def test_perfect_agreement(self) -> None:
        a = [1, 0, 1, 0, 1]
        b = [1, 0, 1, 0, 1]
        assert cohens_kappa(a, b) == pytest.approx(1.0)

    def test_perfect_disagreement_kappa_negative(self) -> None:
        # Pathological: every disagreement.
        a = [1, 1, 1, 0, 0, 0]
        b = [0, 0, 0, 1, 1, 1]
        k = cohens_kappa(a, b)
        assert k < 0

    def test_chance_agreement_near_zero(self) -> None:
        rng = np.random.default_rng(7)
        a = rng.integers(0, 2, 1000).tolist()
        b = rng.integers(0, 2, 1000).tolist()
        # With independent random raters, kappa should be near 0.
        k = cohens_kappa(a, b)
        assert abs(k) < 0.1

    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError):
            cohens_kappa([1, 0], [1])


class TestFleissKappa:
    def test_perfect_agreement(self) -> None:
        ratings = [[1, 1, 1], [0, 0, 0], [1, 1, 1]]
        assert fleiss_kappa(ratings) == pytest.approx(1.0)

    def test_chance_agreement_near_zero(self) -> None:
        rng = np.random.default_rng(11)
        ratings = [rng.integers(0, 3, 4).tolist() for _ in range(200)]
        k = fleiss_kappa(ratings)
        assert abs(k) < 0.15

    def test_uneven_raters_raises(self) -> None:
        with pytest.raises(ValueError):
            fleiss_kappa([[1, 1, 1], [0, 0]])


class TestKrippendorffAlpha:
    def test_perfect_nominal(self) -> None:
        ratings = [[1.0, 1.0, 1.0], [0.0, 0.0, 0.0]]
        assert krippendorff_alpha(ratings, level="nominal") == pytest.approx(1.0)

    def test_handles_missing_values(self) -> None:
        ratings = [[1.0, None, 1.0], [0.0, 0.0, None]]
        # Should not raise; should return a value.
        a = krippendorff_alpha(ratings, level="nominal")
        assert -1.0 <= a <= 1.0
