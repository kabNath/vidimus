"""Default persistence: traces written by one process are visible to the CLI in another."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import vidimus
from vidimus.config import get_config, reset_config
from vidimus.storage.memory import InMemoryStore

pytest.importorskip("duckdb")


def _env(home: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "VIDIMUS_STORE"}
    env["VIDIMUS_HOME"] = str(home)
    return env


def _cli(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "vidimus.cli.main", *args],
        env=_env(home),
        capture_output=True,
        text=True,
        timeout=120,
    )


def _write_traces(home: Path, n: int, workspace: str = "acme") -> None:
    """'Terminal 1': an application process that records traces, then exits."""
    code = textwrap.dedent(f"""
        import vidimus
        vidimus.init(workspace={workspace!r})
        @vidimus.audit
        def agent(q): return "a: " + q
        for i in range({n}):
            agent(f"q{{i}}")
    """)
    r = subprocess.run([sys.executable, "-c", code], env=_env(home), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_default_store_is_duckdb_file_in_workspace_dir(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("VIDIMUS_STORE", raising=False)
    reset_config()
    cfg = vidimus.init(workspace="acme", home_dir=tmp_path)
    assert type(cfg.store).__name__ == "DuckDBStore"
    assert (tmp_path / "workspaces" / "acme" / "traces.duckdb").exists()
    cfg.store.close()
    reset_config()


def test_memory_store_remains_available(tmp_path: Path) -> None:
    reset_config()
    assert isinstance(
        vidimus.init(workspace="t", home_dir=tmp_path, store="memory").store, InMemoryStore
    )
    assert isinstance(get_config().store, InMemoryStore)
    reset_config()


def test_attest_prove_export_verify_across_terminals(tmp_path: Path) -> None:
    home = tmp_path / "home"
    assert _cli(home, "init", "--workspace", "acme").returncode == 0
    _write_traces(home, 7)  # terminal 1 (then exits)

    report, traces = tmp_path / "r.json", tmp_path / "t.jsonl"
    r = _cli(home, "attest", "--since", "1h", "--output", str(report), "--seed", "3")  # terminal 2
    assert r.returncode == 0, r.stdout + r.stderr
    att = json.loads(report.read_text(encoding="utf-8"))
    assert att["workspace"] == "acme" and att["trace_count"] == 7

    r = _cli(home, "export", "--against", str(report), "-o", str(traces))  # terminal 3
    assert r.returncode == 0, r.stdout + r.stderr
    r = _cli(home, "verify", str(report), "--traces", str(traces))  # terminal 4
    assert r.returncode == 0 and "Merkle root matches 7 traces" in r.stdout, r.stdout + r.stderr

    first = json.loads(traces.read_text(encoding="utf-8").splitlines()[0])["trace_id"]
    r = _cli(home, "prove", first, "--against", str(report))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Inclusion proof" in r.stdout


def test_init_does_not_wipe_existing_traces_unless_reset(tmp_path: Path) -> None:
    home = tmp_path / "home"
    assert _cli(home, "init", "--workspace", "acme").returncode == 0
    _write_traces(home, 4)
    assert _cli(home, "init", "--workspace", "acme").returncode == 0  # second init: no wipe
    report = tmp_path / "r.json"
    r = _cli(home, "attest", "--since", "1h", "--output", str(report))
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(report.read_text(encoding="utf-8"))["trace_count"] == 4

    r = _cli(home, "init", "--workspace", "acme", "--reset", "--yes")
    assert r.returncode == 0, r.stdout + r.stderr
    r = _cli(home, "attest", "--since", "1h", "--output", str(report))
    assert r.returncode == 1 and "No traces found" in r.stdout  # wiped


def test_cli_uses_workspace_saved_by_init(tmp_path: Path) -> None:
    home = tmp_path / "home"
    assert _cli(home, "init", "--workspace", "acme-prod").returncode == 0
    _write_traces(home, 2, workspace="acme-prod")
    report = tmp_path / "r.json"
    assert _cli(home, "attest", "--since", "1h", "--output", str(report)).returncode == 0
    assert json.loads(report.read_text(encoding="utf-8"))["workspace"] == "acme-prod"


@pytest.mark.parametrize("encoding", ["cp1252", "ascii", "utf-8"])
def test_cli_prints_under_any_stdout_encoding(tmp_path: Path, encoding: str) -> None:
    """A legacy console code page (cp1252 on Windows) must not crash the CLI's glyphs."""
    env = {**_env(tmp_path), "PYTHONIOENCODING": encoding, "PYTHONUTF8": "0"}
    r = subprocess.run(
        [sys.executable, "-m", "vidimus.cli.main", "init", "--workspace", "acme"],
        env=env,
        capture_output=True,
        timeout=120,
    )
    assert r.returncode == 0, r.stderr.decode(encoding, "replace")
    out = r.stdout.decode(encoding)
    assert "Initialized workspace" in out
    assert ("✓" in out) == (encoding == "utf-8")
