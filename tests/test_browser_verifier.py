"""verifier/index.html must agree with the Python implementation, byte for byte where it matters."""

from __future__ import annotations

import json
import math
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from vidimus.audit.attest import verify
from vidimus.audit.canonical import canonicalize
from vidimus.audit.schemas import Attestation

ROOT = Path(__file__).resolve().parent.parent
VERIFIER = ROOT / "verifier"
EXAMPLES = VERIFIER / "examples"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def _node(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", str(VERIFIER / "test.mjs"), *args],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _fp() -> str:
    lines = (EXAMPLES / "trusted-keys.txt").read_text().splitlines()
    return next(x for x in lines if x and not x.startswith("#")).strip()


def test_node_suite_passes_including_the_tampered_case() -> None:
    r = _node()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "TAMPERED: signature fails and the attestation is rejected" in r.stdout


def test_canonical_form_matches_python_for_random_values() -> None:
    rng = random.Random(1234)
    floats = [
        1e-05,
        0.0001,
        0.00012345,
        1.5e-07,
        1e16,
        1e22,
        0.1,
        0.30000000000000004,
        12345.678,
        -2.5e-10,
        123456789012345680.0,
        5e-324,
        1.7976931348623157e308,
        0.5,
        1.0,
        100.0,
    ]
    floats += [rng.uniform(-1, 1) * 10 ** rng.randint(-12, 20) for _ in range(500)]
    values: list[object] = [f for f in floats if math.isfinite(f)]
    values += [
        3,
        -7,
        0,
        2**53 - 1,
        "plain",
        'quo"te\\ \n\t\r\b\f \x01\x1f é 中 \U0001f600',
        {"b": [1, 2.5, None, True], "a": {"z": 1, "y": "é"}, "ä": 1, "Z": 2},
        [{"k": 1e-05}, [], {}],
    ]
    r = _node("--canon", stdin=json.dumps(values, ensure_ascii=False))
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    for v, g in zip(values, got, strict=True):
        assert canonicalize(v).decode() == g, f"{v!r}: python={canonicalize(v).decode()!r} js={g!r}"


@pytest.mark.parametrize("name", ["valid.json", "tampered.json", "wrong-key.json"])
def test_examples_get_the_same_verdict_in_python_and_in_the_page(name: str) -> None:
    att = Attestation.model_validate_json((EXAMPLES / name).read_text())
    for pins in (None, [_fp()]):
        ok_py, _, warnings = verify(att, trusted_keys=pins)
        args = ["--verify", str(EXAMPLES / name)] + (["--pin", pins[0]] if pins else [])
        js = json.loads(_node(*args).stdout)
        assert js["ok"] == ok_py, (name, pins, js)
        assert (js["status"]["pinned"] == "not_checked") == (pins is None)
        if pins is None:
            assert any("not pinned" in w for w in warnings)


def test_legacy_attestation_is_verified_by_the_page_too(tmp_path: Path) -> None:
    import vidimus
    from tests.test_merkle_scheme import _legacy_attestation
    from vidimus.config import reset_config

    reset_config()
    vidimus.init(workspace="sch-ws", judges=["stub:a", "stub:b"], home_dir=tmp_path, store="memory")
    raw, _, _ = _legacy_attestation(5)
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(raw))
    js = json.loads(_node("--verify", str(path)).stdout)
    assert js["ok"] and js["status"]["signature"] == "pass" and js["status"]["scheme"] == "warn"
    raw["trace_count"] += 1
    path.write_text(json.dumps(raw))
    assert json.loads(_node("--verify", str(path)).stdout)["status"]["signature"] == "fail"
