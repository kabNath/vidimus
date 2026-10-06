"""merkle_scheme: new attestations commit to RFC 6962; legacy ones are verified with the old rule."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import vidimus
from vidimus.audit.attest import attest, verify, verify_traces
from vidimus.audit.canonical import canonicalize
from vidimus.audit.keys import generate_keypair
from vidimus.audit.schemas import Attestation
from vidimus.audit.signing import sign_hex
from vidimus.config import get_config, reset_config


@pytest.fixture(autouse=True)
def fresh_config(tmp_path: Path) -> None:
    reset_config()
    vidimus.init(workspace="sch-ws", judges=["stub:a", "stub:b"], home_dir=tmp_path)


def _legacy_root(leaves: list[bytes]) -> str:
    """The pre-0.1.0a3 rule: duplicate the last node of an odd level."""
    h = lambda b: hashlib.sha256(b).digest()  # noqa: E731
    level = [h(b"\x00" + d) for d in leaves]
    while len(level) > 1:
        level = [
            h(b"\x01" + level[i] + (level[i + 1] if i + 1 < len(level) else level[i]))
            for i in range(0, len(level), 2)
        ]
    return level[0].hex()


def _traces(n: int):  # type: ignore[no-untyped-def]
    @vidimus.audit
    def agent(q: str) -> str:
        return f"a: {q}"

    for i in range(n):
        agent(f"q{i}")
    end = datetime.now(timezone.utc) + timedelta(seconds=1)
    return end - timedelta(hours=1), end


def test_new_attestation_declares_and_signs_scheme() -> None:
    start, end = _traces(5)
    kp = generate_keypair()
    att = attest(["hallucination"], start, end, kp, seed=1)
    assert att.merkle_scheme == "rfc6962-v1"
    assert verify(att, trusted_keys=[kp.fingerprint])[0]
    # Downgrading the declared scheme must break the signature.
    downgraded = att.model_copy(update={"merkle_scheme": "legacy-duplicate"})
    ok, issues, _ = verify(downgraded)
    assert not ok and any("signature" in i for i in issues)


def _legacy_attestation(n: int):  # type: ignore[no-untyped-def]
    start, end = _traces(n)
    kp = generate_keypair()
    from vidimus.audit.attest import leaf_bytes

    traces = get_config().store.list_traces("sch-ws", start, end)
    root = _legacy_root([leaf_bytes(t) for t in traces])
    modern = attest(["hallucination"], start, end, kp, seed=1)
    d = modern.model_dump(mode="json")
    d.pop("merkle_scheme")  # legacy attestations had no such field
    d["merkle_root"] = root
    d["signature"] = ""
    d["signature"] = sign_hex(kp.private_key, canonicalize(d))
    return json.loads(json.dumps(d)), traces, kp


def test_legacy_attestation_without_field_loads_as_legacy_and_verifies_with_warning() -> None:
    raw, traces, _ = _legacy_attestation(5)
    assert "merkle_scheme" not in raw
    att = Attestation.model_validate(raw)
    assert att.merkle_scheme == "legacy-duplicate"
    ok, issues, warnings = verify(att)
    assert ok, issues
    assert any("legacy" in w and "Merkle" in w for w in warnings)
    # Re-serialising a legacy attestation must keep it verifiable.
    again = Attestation.model_validate_json(att.model_dump_json())
    assert verify(again)[0]


def test_legacy_root_recomputed_with_legacy_rule_not_new_rule() -> None:
    raw, traces, _ = _legacy_attestation(5)  # odd count: the two rules differ
    att = Attestation.model_validate(raw)
    assert verify_traces(att, traces) == []
    forced_new = att.model_copy(update={"merkle_scheme": "rfc6962-v1"})
    assert verify_traces(forced_new, traces) != []


def test_anchor_hash_of_legacy_attestation_ignores_the_new_field() -> None:
    from vidimus.audit.anchor import compute_anchor_hash

    raw, _, _ = _legacy_attestation(3)
    att = Attestation.model_validate(raw)
    d = dict(raw)
    d["signature"] = ""
    expected = hashlib.sha256(
        bytes.fromhex(raw["merkle_root"]) + hashlib.sha256(canonicalize(d)).digest()
    ).digest()
    assert compute_anchor_hash(att) == expected
