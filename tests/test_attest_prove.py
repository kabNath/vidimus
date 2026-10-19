"""End-to-end: the proof produced by `prove` must rebuild the root signed by `attest`."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

import vidimus
from vidimus.audit.attest import attest
from vidimus.audit.keys import generate_keypair
from vidimus.cli.main import cli
from vidimus.config import get_config, reset_config


@pytest.fixture(autouse=True)
def fresh_config(tmp_path: Path) -> None:
    reset_config()
    vidimus.init(workspace="prove-ws", judges=["stub:a", "stub:b"], home_dir=tmp_path)


def _attested(n: int, tmp_path: Path):  # type: ignore[no-untyped-def]
    @vidimus.audit
    def agent(q: str) -> str:
        return f"a: {q}"

    for i in range(n):
        agent(f"q{i}")
    end = datetime.now(timezone.utc) + timedelta(seconds=1)
    att = attest(["hallucination"], end - timedelta(hours=1), end, generate_keypair(), seed=1)
    path = tmp_path / "att.json"
    path.write_text(att.model_dump_json(), encoding="utf-8", newline="\n")
    return att, path


@pytest.mark.parametrize("n", [1, 2, 5, 8])
def test_cli_prove_reconstructs_signed_root(n: int, tmp_path: Path) -> None:
    att, path = _attested(n, tmp_path)
    traces = get_config().store.list_traces(att.workspace, att.period_start, att.period_end)
    for t in traces:
        r = CliRunner().invoke(cli, ["prove", t.trace_id, "--against", str(path)])
        assert r.exit_code == 0, r.output


def test_proof_verifies_against_signed_root_via_api(tmp_path: Path) -> None:
    from vidimus.audit.attest import leaf_bytes
    from vidimus.audit.merkle import MerkleTree, verify_inclusion

    att, _ = _attested(7, tmp_path)
    traces = get_config().store.list_traces(att.workspace, att.period_start, att.period_end)
    tree = MerkleTree([leaf_bytes(t) for t in traces])
    assert tree.root_hex == att.merkle_root
    for i in range(len(traces)):
        assert verify_inclusion(tree.proof(i), bytes.fromhex(att.merkle_root))
