"""Regenerate verifier/examples/*.json (run from the repo root: python verifier/make_examples.py).

The two issuer keys are derived from public seed strings. They are DEMO keys, published on purpose:
never use them for anything real.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import vidimus
from vidimus.audit.attest import attest
from vidimus.audit.keys import KeyPair, _fingerprint
from vidimus.config import reset_config
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

OUT = Path(__file__).resolve().parent / "examples"


def demo_key(seed: str) -> KeyPair:
    priv = Ed25519PrivateKey.from_private_bytes(hashlib.sha256(seed.encode()).digest())
    pub = priv.public_key()
    return KeyPair(private_key=priv, public_key=pub, fingerprint=_fingerprint(pub))


def main() -> None:
    reset_config()
    vidimus.init(workspace="demo", judges=["stub:a", "stub:b", "stub:c"],
                 home_dir=tempfile.mkdtemp(), store="memory")

    @vidimus.audit
    def agent(q: str) -> str:
        return f"answer to {q}"

    for i in range(12):
        agent(f"question {i}")
    end = datetime.now(timezone.utc) + timedelta(seconds=1)
    start = end - timedelta(hours=1)

    issuer, other = demo_key("vidimus-demo-issuer"), demo_key("vidimus-demo-other-issuer")
    valid = attest(["hallucination"], start, end, issuer, seed=7)
    forged = attest(["hallucination"], start, end, other, seed=7)

    OUT.mkdir(exist_ok=True)
    (OUT / "valid.json").write_text(valid.model_dump_json(indent=2) + "\n")
    # Altered after signing: the headline number is edited, still inside its interval.
    d = json.loads(valid.model_dump_json())
    m = d["metrics"][0]
    m["point_estimate"] = round((m["ci_low"] + m["point_estimate"]) / 2, 4)
    (OUT / "tampered.json").write_text(json.dumps(d, indent=2) + "\n")
    # Perfectly valid signature... from someone else.
    (OUT / "wrong-key.json").write_text(forged.model_dump_json(indent=2) + "\n")
    (OUT / "trusted-keys.txt").write_text(
        f"# Fingerprint of the demo issuer that signed valid.json and tampered.json\n{issuer.fingerprint}\n"
    )
    print("issuer fingerprint:", issuer.fingerprint)
    print("other  fingerprint:", other.fingerprint)


if __name__ == "__main__":
    main()
