"""Tests for issuer-key pinning in verify() and the CLI."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

import vidimus
from vidimus.audit.attest import attest, verify
from vidimus.audit.keys import generate_keypair
from vidimus.cli.main import cli
from vidimus.config import reset_config

NOT_PINNED = "issuer key not pinned: signature proves integrity, not identity"


@pytest.fixture(autouse=True)
def fresh_config(tmp_path: Path) -> None:
    reset_config()
    vidimus.init(workspace="pin-ws", judges=["stub:a", "stub:b"], home_dir=tmp_path)


def _make(kp):  # type: ignore[no-untyped-def]
    @vidimus.audit
    def agent(q: str) -> str:
        return f"a: {q}"

    for i in range(5):
        agent(f"q{i}")
    end = datetime.now(timezone.utc) + timedelta(seconds=1)
    return attest(["hallucination"], end - timedelta(hours=1), end, kp, seed=1)


class TestPinning:
    def test_unpinned_warns(self) -> None:
        att = _make(generate_keypair())
        ok, issues, warnings = verify(att)
        assert ok, issues
        assert NOT_PINNED in warnings

    def test_pinned_by_fingerprint_ok(self) -> None:
        kp = generate_keypair()
        ok, issues, warnings = verify(_make(kp), trusted_keys=[kp.fingerprint])
        assert ok, issues
        assert NOT_PINNED not in warnings

    def test_pinned_by_public_key_hex_ok(self) -> None:
        kp = generate_keypair()
        ok, issues, warnings = verify(_make(kp), trusted_keys=[kp.public_key_hex.upper()])
        assert ok, issues
        assert NOT_PINNED not in warnings

    def test_forged_with_other_key_refused_when_pinned(self) -> None:
        trusted, attacker = generate_keypair(), generate_keypair()
        forged = _make(attacker)  # perfectly self-consistent attestation
        assert verify(forged)[0]  # unpinned: integrity only, passes
        ok, issues, _ = verify(forged, trusted_keys=[trusted.fingerprint])
        assert not ok
        assert any("not in trusted keys" in i for i in issues)

    def test_empty_trusted_list_refuses(self) -> None:
        ok, issues, _ = verify(_make(generate_keypair()), trusted_keys=[])
        assert not ok
        assert any("not in trusted keys" in i for i in issues)


class TestCli:
    def _write(self, tmp_path: Path, kp) -> Path:  # type: ignore[no-untyped-def]
        p = tmp_path / "report.json"
        p.write_text(_make(kp).model_dump_json(), encoding="utf-8", newline="\n")
        return p

    def test_cli_unpinned_prints_warning(self, tmp_path: Path) -> None:
        report = self._write(tmp_path, generate_keypair())
        r = CliRunner().invoke(cli, ["verify", str(report)])
        assert r.exit_code == 0, r.output
        assert "issuer key not pinned" in r.output

    def test_cli_trusted_key_ok_and_forged_refused(self, tmp_path: Path) -> None:
        good, evil = generate_keypair(), generate_keypair()
        report = self._write(tmp_path, evil)
        r = CliRunner().invoke(cli, ["verify", str(report), "--trusted-key", good.fingerprint])
        assert r.exit_code == 1
        r = CliRunner().invoke(cli, ["verify", str(report), "--trusted-key", evil.fingerprint])
        assert r.exit_code == 0, r.output

    def test_cli_trusted_keys_file(self, tmp_path: Path) -> None:
        kp = generate_keypair()
        report = self._write(tmp_path, kp)
        keys = tmp_path / "keys.txt"
        keys.write_text(
            f"# pinned issuers\n\n{kp.fingerprint}  # prod\n", encoding="utf-8", newline="\n"
        )
        r = CliRunner().invoke(cli, ["verify", str(report), "--trusted-keys-file", str(keys)])
        assert r.exit_code == 0, r.output
        assert "not pinned" not in r.output
