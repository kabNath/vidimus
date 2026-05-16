"""End-to-end demo: instrument an agent, generate an attestation, verify it.

Run with:
    python examples/basic_agent.py

Output: a signed attestation.json that you can then verify with:
    vidimus verify attestation.json
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import vidimus
from vidimus.audit.attest import attest, verify
from vidimus.audit.keys import generate_keypair


def main() -> None:
    # 1) Configure Vidimus runtime.
    vidimus.init(
        workspace="demo-agent",
        judges=["stub:judge-1", "stub:judge-2", "stub:judge-3"],
    )

    # 2) Instrument an agent. In a real app this could be calling OpenAI,
    #    Anthropic, a local LLM via Ollama, or chaining LangChain/CrewAI.
    @vidimus.audit
    def my_agent(query: str) -> str:
        return f"echo: {query}"

    print("Generating traces...")
    for i in range(50):
        my_agent(f"customer question #{i}")

    # 3) Generate a signed attestation over the last hour.
    keypair = generate_keypair()
    end = datetime.now(timezone.utc) + timedelta(seconds=1)
    start = end - timedelta(hours=1)

    attestation = attest(
        metrics=["hallucination", "relevance"],
        period_start=start,
        period_end=end,
        keypair=keypair,
        seed=42,  # reproducible CIs
    )

    # 4) Persist the attestation.
    out = Path("attestation.json")
    out.write_text(attestation.model_dump_json(indent=2))
    print(f"\n✓ Attestation written to {out.resolve()}")
    print(f"  workspace    : {attestation.workspace}")
    print(f"  trace count  : {attestation.trace_count}")
    print(f"  Merkle root  : {attestation.merkle_root[:32]}...")
    print(f"  issuer fp    : {attestation.issuer_pubkey_fingerprint[:32]}...")
    print(f"  signature    : {attestation.signature[:32]}... (Ed25519, 64 bytes)")
    print()
    print("  Metrics:")
    for m in attestation.metrics:
        kappa = f"κ={m.judge_agreement:.2f}" if m.judge_agreement is not None else "n/a"
        print(
            f"    {m.name:20} {m.point_estimate:6.2%}  "
            f"CI [{m.ci_low:6.2%}, {m.ci_high:6.2%}]  n={m.n}  {kappa}"
        )

    # 5) Offline verification (this is what a regulator or auditor would run).
    print("\nVerifying offline...")
    ok, issues, warnings = verify(attestation)

    if ok:
        print("✓ Cryptographic verification: PASSED")
        if warnings:
            print("  Non-fatal warnings:")
            for w in warnings:
                print(f"    - {w}")
    else:
        print("✗ Cryptographic verification: FAILED")
        for issue in issues:
            print(f"    - {issue}")

    # 6) Demonstrate tamper detection.
    print("\nNow let's tamper with the attestation and verify again...")
    tampered = attestation.model_copy(update={"trace_count": 9999})
    ok, issues, _ = verify(tampered)
    if not ok:
        print(f"✓ Tampering detected: {issues[0]}")
    else:
        print("✗ Tampering went undetected (this should not happen!)")


if __name__ == "__main__":
    main()
