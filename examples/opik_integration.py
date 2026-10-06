"""Vidimus alongside Comet Opik.

This example demonstrates the **complementary** pattern: an agent is
instrumented by both Opik (for the dashboard, datasets, prompt playground)
*and* Vidimus (for the cryptographic attestation layer that Opik doesn't
provide).

Both tools coexist via OpenTelemetry, so the trace flows out to Opik in one
direction and into Vidimus in another. Neither tool replaces the other:

  Opik         provides: UI, dashboards, datasets, prompt versioning,
                          generic LLMOps platform features
  Vidimus      provides: tamper-evident traces, calibrated uncertainty,
                          Ed25519 attestations, offline third-party verification

This file shows the integration pattern with concrete code, gracefully
falling back to a clear message if Opik is not installed.

Setup:
    pip install vidimus opik

    # Configure Opik (one of):
    #   - Cloud:     opik configure --api-key <your-key>
    #   - Self-host: opik configure --use-local

Run:
    python examples/opik_integration.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import vidimus
from vidimus.audit import attest, verify
from vidimus.audit.keys import generate_keypair


# ─────────────────────────────────────────────────────────────────────────────
# Detect Opik availability
# ─────────────────────────────────────────────────────────────────────────────


def _opik_available() -> bool:
    try:
        import opik  # noqa: F401
        return True
    except ImportError:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Dual-instrumented agent
# ─────────────────────────────────────────────────────────────────────────────


def make_dual_agent():
    """Return an agent function decorated by BOTH Opik and Vidimus.

    The order matters: outer decorators are called first, so put Opik on the
    outside (so it sees the original input) and Vidimus on the inside (so it
    audits the post-validation call).
    """
    if _opik_available():
        import opik

        @opik.track(name="my_agent")
        @vidimus.audit
        def agent(query: str) -> str:
            # In real use: this is where your LLM call goes.
            # Both Opik and Vidimus will record the same input/output.
            return f"Response to: {query}"

        return agent

    # Fallback: vidimus only
    @vidimus.audit
    def agent(query: str) -> str:
        return f"Response to: {query}"

    return agent


# ─────────────────────────────────────────────────────────────────────────────
# Main flow
# ─────────────────────────────────────────────────────────────────────────────


def main() -> None:
    print("=" * 70)
    print("Vidimus + Comet Opik integration")
    print("=" * 70)

    if _opik_available():
        print("\n✓ Opik detected — traces will flow to Opik AND Vidimus in parallel")
        opik_workspace = os.environ.get("OPIK_WORKSPACE", "default")
        print(f"  Opik workspace: {opik_workspace}")
    else:
        print("\n⚠ Opik not installed — running with Vidimus only")
        print("  To enable the dual-instrumentation pattern:")
        print("      pip install opik")
        print("      opik configure --api-key <your-key>")

    # Initialize Vidimus
    vidimus.init(
        workspace="opik-integration-demo",
        judges=["stub:judge-a", "stub:judge-b", "stub:judge-c"],
    )

    # Build the dual-instrumented agent
    agent = make_dual_agent()

    # Generate some traffic
    queries = [
        "What is the capital of France?",
        "Summarize the EU AI Act in one sentence.",
        "Translate 'hello' to Japanese.",
        "What is 2 + 2?",
        "Explain how Merkle trees work.",
    ]

    print(f"\nRunning {len(queries)} queries through the dual-instrumented agent...")
    for q in queries:
        agent(q)

    # Generate the Vidimus attestation (Opik's dashboard already has the
    # traces, but only Vidimus produces a signed audit artifact)
    print("\nGenerating Vidimus attestation...")
    keypair = generate_keypair()
    end = datetime.now(timezone.utc) + timedelta(seconds=1)
    start = end - timedelta(hours=1)

    attestation = attest(
        metrics=["relevance", "accuracy"],
        period_start=start,
        period_end=end,
        keypair=keypair,
        seed=42,
    )

    out_path = Path("opik_attestation.json")
    out_path.write_text(attestation.model_dump_json(indent=2))
    print(f"  → {out_path}")
    print(f"  Workspace:   {attestation.workspace}")
    print(f"  Trace count: {attestation.trace_count}")
    print(f"  Merkle root: {attestation.merkle_root[:32]}...")
    print(f"  Signature:   {attestation.signature[:32]}...")

    # Verify
    print("\nVerifying attestation offline...")
    ok, issues, warnings = verify(attestation)
    if ok:
        print("  ✓ Cryptographic verification PASSED")
    else:
        print("  ✗ Verification FAILED")
        for i in issues:
            print(f"    - {i}")
    for w in warnings:
        print(f"  ⚠ {w}")

    print("\n" + "=" * 70)
    print("If Opik is configured, the same traces are visible in the Opik UI.")
    print("Vidimus complements Opik by adding the signed attestation artifact.")
    print("=" * 70)


if __name__ == "__main__":
    main()
