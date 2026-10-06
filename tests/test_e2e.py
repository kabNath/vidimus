"""End-to-end tests: generate traces, build an attestation, verify it offline."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import vidimus
from vidimus.audit.attest import attest, verify
from vidimus.audit.keys import generate_keypair
from vidimus.audit.schemas import Attestation
from vidimus.config import reset_config


@pytest.fixture(autouse=True)
def fresh_config(tmp_path: Path) -> None:
    """Reset Vidimus config before each test with an isolated home dir."""
    reset_config()
    vidimus.init(
        workspace="test-ws",
        judges=["stub:a", "stub:b", "stub:c"],
        home_dir=tmp_path,
    )


def _seed_traces(n: int = 20) -> None:
    @vidimus.audit
    def fake_agent(q: str) -> str:
        return f"answer to: {q}"

    for i in range(n):
        fake_agent(f"question {i}")


class TestEndToEnd:
    def test_full_attest_verify_cycle(self) -> None:
        _seed_traces(20)
        kp = generate_keypair()
        end = datetime.now(timezone.utc) + timedelta(seconds=1)
        start = end - timedelta(hours=1)

        att = attest(
            metrics=["hallucination", "relevance"],
            period_start=start,
            period_end=end,
            keypair=kp,
            seed=42,
        )

        assert att.workspace == "test-ws"
        assert att.trace_count == 20
        assert len(att.merkle_root) == 64
        assert len(att.signature) == 128
        assert len(att.metrics) == 2

        for m in att.metrics:
            assert m.n == 20
            assert m.ci_low <= m.point_estimate <= m.ci_high
            assert len(m.judges) == 3

        ok, issues, _warnings = verify(att)
        assert ok, f"verification failed: {issues}"

    def test_round_trip_through_json(self) -> None:
        _seed_traces(10)
        kp = generate_keypair()
        end = datetime.now(timezone.utc) + timedelta(seconds=1)
        start = end - timedelta(hours=1)

        att = attest(
            metrics=["hallucination"],
            period_start=start,
            period_end=end,
            keypair=kp,
            seed=7,
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "att.json"
            path.write_text(att.model_dump_json(indent=2))

            data = json.loads(path.read_text())
            loaded = Attestation.model_validate(data)

            ok, issues, _warnings = verify(loaded)
            assert ok, f"verification failed: {issues}"

    def test_tampered_attestation_rejected(self) -> None:
        _seed_traces(5)
        kp = generate_keypair()
        end = datetime.now(timezone.utc) + timedelta(seconds=1)
        start = end - timedelta(hours=1)

        att = attest(
            metrics=["hallucination"],
            period_start=start,
            period_end=end,
            keypair=kp,
            seed=0,
        )

        # Tamper with the merkle root.
        tampered = att.model_copy(update={"merkle_root": "0" * 64})
        ok, issues, _ = verify(tampered)
        assert not ok
        assert any("signature" in i.lower() for i in issues)

    def test_tampered_metric_rejected(self) -> None:
        _seed_traces(5)
        kp = generate_keypair()
        end = datetime.now(timezone.utc) + timedelta(seconds=1)
        start = end - timedelta(hours=1)

        att = attest(
            metrics=["hallucination"],
            period_start=start,
            period_end=end,
            keypair=kp,
            seed=0,
        )

        # Tamper with the metric's name (guaranteed to differ from the original
        # "hallucination" value, so the canonical JSON changes and the
        # signature must no longer verify).
        bad_metric = att.metrics[0].model_copy(update={"name": "fabricated_metric"})
        tampered = att.model_copy(update={"metrics": [bad_metric]})
        ok, _, _ = verify(tampered)
        assert not ok

    def test_empty_window_raises(self) -> None:
        _seed_traces(5)
        kp = generate_keypair()
        # Window in the past with no traces.
        end = datetime(2020, 1, 2, tzinfo=timezone.utc)
        start = datetime(2020, 1, 1, tzinfo=timezone.utc)

        with pytest.raises(ValueError):
            attest(
                metrics=["hallucination"],
                period_start=start,
                period_end=end,
                keypair=kp,
            )

    def test_reproducible_with_same_seed(self) -> None:
        # Note: traces have generated UUIDs, so two runs with the same seed
        # but different traces will produce different Merkle roots. To test
        # bootstrap reproducibility, we seed once, attest twice on the same
        # traces.
        _seed_traces(20)
        kp = generate_keypair()
        end = datetime.now(timezone.utc) + timedelta(seconds=1)
        start = end - timedelta(hours=1)

        a1 = attest(
            metrics=["hallucination"],
            period_start=start,
            period_end=end,
            keypair=kp,
            seed=99,
        )
        a2 = attest(
            metrics=["hallucination"],
            period_start=start,
            period_end=end,
            keypair=kp,
            seed=99,
        )
        # Same traces + same seed -> same CI.
        assert a1.metrics[0].ci_low == a2.metrics[0].ci_low
        assert a1.metrics[0].ci_high == a2.metrics[0].ci_high
        assert a1.merkle_root == a2.merkle_root
