"""
Vidimus + Opik integration example.

This example demonstrates the canonical Vidimus pattern: running on top of an
existing Opik observability setup to add cryptographic provenance and calibrated
uncertainty without replacing anything.

The architecture is:

    Your agent ──▶ Opik (dashboards, traces, replay)
                │
                └──▶ Vidimus (Merkle tree, signed attestations)

Both consume the same OpenTelemetry spans. Opik handles the operational
observability story; Vidimus handles the audit / trust story.

NOTE: This example uses stub Opik calls so it runs without an Opik account.
In production you would `pip install opik` and configure it as usual.

Requirements:
    pip install vidimus
    # pip install opik   # uncomment for real Opik integration
"""

from __future__ import annotations

import time
from typing import Any

import vidimus

# ---------------------------------------------------------------------------
# Stub Opik client — replace with the real `import opik` in production.
# ---------------------------------------------------------------------------
class _StubOpikClient:
    """Minimal stand-in for opik.Opik() so this example runs offline."""

    def trace(self, name: str, input: Any, output: Any, metadata: dict[str, Any]) -> None:
        # In real Opik this sends to the dashboard. We just print.
        print(f"  [opik] traced: name={name!r} model={metadata.get('model')}")


opik_client = _StubOpikClient()


# ---------------------------------------------------------------------------
# The agent — instrumented for BOTH Opik and Vidimus.
# ---------------------------------------------------------------------------
vidimus.init(workspace="opik-integration-demo")


@vidimus.audit
def rag_agent(question: str) -> str:
    """Answer a question using a (faked) RAG pipeline.

    The @vidimus.audit decorator captures the full input/output for the
    tamper-evident Merkle store. We separately push the same call to Opik
    for the operational dashboard.
    """
    # 1. Simulate retrieval
    time.sleep(0.01)
    retrieved_docs = [
        f"Doc about {question.split()[0]}: ...",
        f"Doc about {question.split()[-1]}: ...",
    ]

    # 2. Simulate LLM call
    time.sleep(0.05)
    answer = f"Based on {len(retrieved_docs)} retrieved documents, the answer to {question!r} is 42."

    # 3. Also send to Opik (dual-instrumented)
    opik_client.trace(
        name="rag_agent",
        input={"question": question, "retrieved_docs": retrieved_docs},
        output=answer,
        metadata={"model": "gpt-4o-mini", "cost_usd": 0.0012},
    )

    return answer


# ---------------------------------------------------------------------------
# Drive it
# ---------------------------------------------------------------------------
def main() -> None:
    print("Running dual-instrumented agent (Opik + Vidimus)...\n")

    questions = [
        "What is the capital of France?",
        "How does photosynthesis work?",
        "What is the speed of light?",
        "Who wrote Hamlet?",
        "What is the meaning of life?",
    ]

    for q in questions:
        print(f"Q: {q}")
        a = rag_agent(q)
        print(f"A: {a[:80]}...\n")

    # Now generate a Vidimus attestation over everything we just ran.
    print("Generating Vidimus attestation...")
    attestation = vidimus.attest(
        workspace="opik-integration-demo",
        judges=[],  # no LLM judges for this offline example
    )
    print(f"  Merkle root: {attestation.merkle_root[:16]}...")
    print(f"  Trace count: {attestation.trace_count}")
    print(f"  Signed by:   {attestation.issuer_pubkey_fingerprint[:16]}...")

    # Save and verify
    attestation.save("opik_integration_report.json")
    print("\nAttestation saved to opik_integration_report.json")

    ok, issues, warnings = vidimus.verify("opik_integration_report.json")
    print(f"Verification: {'PASS' if ok else 'FAIL'}")
    if warnings:
        print(f"  Warnings: {warnings}")


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Why this matters
# ---------------------------------------------------------------------------
#
# With Opik alone, your traces live in Opik's database. If your auditor asks
# whether the data was modified after the fact, you have to argue from
# infrastructure controls ("only our SREs have DB access, here are the audit
# logs of the audit logs..."). That argument is fragile.
#
# With Vidimus on top, the same agent run produces a signed attestation that:
#   - has a Merkle root over every trace (modification is detectable)
#   - carries the public-key fingerprint of the signer (forgery is impossible
#     without the private key)
#   - is verifiable offline by anyone, with no trust in Vidimus or in you
#
# You keep all the Opik benefits (dashboards, replay, debugging) AND gain a
# portable cryptographic proof. That is the design goal: not "replace your
# observability tool", but "add the trust layer it cannot provide."
