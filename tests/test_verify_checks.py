"""verify must only claim what it actually checked: Merkle recomputation and on-chain anchor."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

import vidimus
from vidimus.audit.attest import attest
from vidimus.audit.keys import generate_keypair
from vidimus.audit.schemas import OnchainAnchor
from vidimus.audit.signing import sign_hex
from vidimus.cli.main import cli
from vidimus.config import reset_config


@pytest.fixture(autouse=True)
def fresh_config(tmp_path: Path) -> None:
    reset_config()
    vidimus.init(workspace="chk-ws", judges=["stub:a", "stub:b"], home_dir=tmp_path)


def _setup(tmp_path: Path, n: int = 5, kp=None):  # type: ignore[no-untyped-def]
    @vidimus.audit
    def agent(q: str) -> str:
        return f"a: {q}"

    for i in range(n):
        agent(f"q{i}")
    kp = kp or generate_keypair()
    end = datetime.now(timezone.utc) + timedelta(seconds=1)
    att = attest(["hallucination"], end - timedelta(hours=1), end, kp, seed=1)
    report = tmp_path / "report.json"
    report.write_text(att.model_dump_json(), encoding="utf-8", newline="\n")
    return att, report, kp


def _export(tmp_path: Path, report: Path) -> Path:
    out = tmp_path / "traces.jsonl"
    r = CliRunner().invoke(cli, ["export", "--against", str(report), "-o", str(out)])
    assert r.exit_code == 0, r.output
    return out


def _run(*args: str):  # type: ignore[no-untyped-def]
    return CliRunner().invoke(cli, ["verify", *args])


class TestNotCheckedByDefault:
    def test_plain_verify_says_not_checked_and_never_claims_a_match(self, tmp_path: Path) -> None:
        _, report, _ = _setup(tmp_path)
        r = _run(str(report))
        assert r.exit_code == 0, r.output
        assert "Merkle root matches" not in r.output
        assert "not checked" in r.output
        assert r.output.count("not checked") == 1  # no anchor in the report -> "none"


class TestTracesCheck:
    def test_matching_export_passes(self, tmp_path: Path) -> None:
        att, report, _ = _setup(tmp_path)
        traces = _export(tmp_path, report)
        r = _run(str(report), "--traces", str(traces))
        assert r.exit_code == 0, r.output
        assert f"Merkle root matches {att.trace_count} traces" in r.output

    def test_json_array_export_also_accepted(self, tmp_path: Path) -> None:
        _att, report, _ = _setup(tmp_path)
        rows = [
            json.loads(line)
            for line in _export(tmp_path, report).read_text(encoding="utf-8").splitlines()
        ]
        arr = tmp_path / "traces.json"
        arr.write_text(
            json.dumps(rows[::-1]), encoding="utf-8", newline="\n"
        )  # order must not matter
        r = _run(str(report), "--traces", str(arr))
        assert r.exit_code == 0, r.output

    def test_modified_trace_is_detected(self, tmp_path: Path) -> None:
        _, report, _ = _setup(tmp_path)
        traces = _export(tmp_path, report)
        rows = [json.loads(line) for line in traces.read_text(encoding="utf-8").splitlines()]
        rows[2]["output"] = "tampered"
        traces.write_text("\n".join(json.dumps(x) for x in rows), encoding="utf-8", newline="\n")
        r = _run(str(report), "--traces", str(traces))
        assert r.exit_code == 1
        assert "Merkle root" in r.output and "matches" not in r.output.split("Merkle root")[0]

    def test_missing_trace_is_detected(self, tmp_path: Path) -> None:
        _, report, _ = _setup(tmp_path)
        traces = _export(tmp_path, report)
        lines = traces.read_text(encoding="utf-8").splitlines()
        traces.write_text("\n".join(lines[:-1]), encoding="utf-8", newline="\n")
        r = _run(str(report), "--traces", str(traces))
        assert r.exit_code == 1
        assert "trace count" in r.output

    def test_signed_root_that_does_not_match_traces(self, tmp_path: Path) -> None:
        # A validly signed report whose root was swapped before signing.
        att, report, kp = _setup(tmp_path)
        bad = att.model_copy(update={"merkle_root": "00" * 32, "signature": ""})
        bad = bad.model_copy(
            update={"signature": sign_hex(kp.private_key, bad.to_signing_payload())}
        )
        report.write_text(bad.model_dump_json(), encoding="utf-8", newline="\n")
        traces = _export(tmp_path, report.with_name("report.json"))  # window still valid
        assert _run(str(report)).exit_code == 0  # signature alone is fine...
        r = _run(str(report), "--traces", str(traces))
        assert r.exit_code == 1  # ...but recomputation catches it


class TestAnchorCheck:
    def _anchored(self, tmp_path: Path):  # type: ignore[no-untyped-def]
        att, _, kp = _setup(tmp_path)
        anchor = OnchainAnchor(
            chain="bnb-chain",
            chain_id=56,
            contract_address="0x" + "ab" * 20,
            block_number=123,
            tx_hash="0x" + "cd" * 32,
            anchored_at=datetime.now(timezone.utc),
        )
        a = att.model_copy(update={"onchain_anchor": anchor, "signature": ""})
        a = a.model_copy(update={"signature": sign_hex(kp.private_key, a.to_signing_payload())})
        report = tmp_path / "anchored.json"
        report.write_text(a.model_dump_json(), encoding="utf-8", newline="\n")
        return a, report

    def _patch(self, monkeypatch: pytest.MonkeyPatch, event):  # type: ignore[no-untyped-def]
        calls: dict[str, object] = {}

        class FakeAnchorer:
            def __init__(self, rpc_url: str, contract_address: str, **kw: object) -> None:
                calls["rpc"] = rpc_url
                calls["contract"] = contract_address

            def verify_anchor(self, attestation):  # type: ignore[no-untyped-def]
                calls["onchain_anchor_in_hashed_copy"] = attestation.onchain_anchor
                return event

        import importlib

        # `vidimus.audit` is shadowed by the decorator, so resolve the module explicitly.
        monkeypatch.setattr(
            importlib.import_module("vidimus.audit.anchor"), "OnchainAnchorer", FakeAnchorer
        )
        return calls

    def test_anchor_present_but_not_checked(self, tmp_path: Path) -> None:
        _, report = self._anchored(tmp_path)
        r = _run(str(report))
        assert r.exit_code == 0, r.output
        assert "on-chain" in r.output and "not checked" in r.output
        assert "verified" not in r.output

    def test_check_anchor_verified(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _, report = self._anchored(tmp_path)
        ev = SimpleNamespace(block_number=123, tx_hash="cd" * 32, chain_id=56)
        calls = self._patch(monkeypatch, ev)
        r = _run(str(report), "--check-anchor", "--rpc-url", "http://rpc.test")
        assert r.exit_code == 0, r.output
        assert "anchor verified" in r.output
        assert calls["rpc"] == "http://rpc.test"
        assert (
            calls["onchain_anchor_in_hashed_copy"] is None
        )  # anchor hash excludes the anchor field

    def test_check_anchor_not_found_is_fatal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, report = self._anchored(tmp_path)
        self._patch(monkeypatch, None)
        r = _run(str(report), "--check-anchor", "--rpc-url", "http://rpc.test")
        assert r.exit_code == 1

    def test_check_anchor_coordinates_mismatch_is_fatal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, report = self._anchored(tmp_path)
        self._patch(monkeypatch, SimpleNamespace(block_number=999, tx_hash="cd" * 32, chain_id=56))
        r = _run(str(report), "--check-anchor", "--rpc-url", "http://rpc.test")
        assert r.exit_code == 1

    def test_check_anchor_without_rpc_url_errors(self, tmp_path: Path) -> None:
        _, report = self._anchored(tmp_path)
        r = _run(str(report), "--check-anchor")
        assert r.exit_code != 0

    def test_check_anchor_on_report_without_anchor(self, tmp_path: Path) -> None:
        _, report, _ = _setup(tmp_path)
        r = _run(str(report), "--check-anchor", "--rpc-url", "http://rpc.test")
        assert r.exit_code == 0, r.output
        assert "none in report" in r.output
