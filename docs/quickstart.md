# Quickstart

This guide walks you from `pip install` to a verified attestation in under 10 minutes.

## What you'll build

By the end of this tutorial, you'll have:

1. A toy agent instrumented with `@vidimus.audit`
2. A Merkle-chained trace store containing ~20 traces
3. A signed attestation file you can share with anyone
4. Proof that the attestation can be verified offline

## Prerequisites

- Python 3.10 or later
- 5 minutes

No API keys, no external services, no blockchain. This tutorial runs entirely locally.

## Step 1 — Install

```bash
pip install vidimus
```

Verify the install:

```bash
vidimus version
# Vidimus 0.1.0a1
```

## Step 2 — Generate a signing key

```bash
vidimus init
```

This creates `~/.vidimus/` containing:

- `config.toml` — your workspace configuration
- `keys/default.key` — an Ed25519 private key (mode 0600)
- `keys/default.pub` — the matching public key

Inspect the public key:

```bash
vidimus keys list
# Key: default
#   Fingerprint: 4a8d2f...
#   Public key:  -----BEGIN PUBLIC KEY-----...
```

The fingerprint is the SHA-256 of the public key bytes. It will appear in every attestation you sign.

## Step 3 — Instrument a toy agent

Create a file `my_agent.py`:

```python
import vidimus

vidimus.init(workspace="quickstart-demo")

@vidimus.audit
def answer_question(query: str) -> str:
    # In real life, this would call an LLM.
    # For the tutorial, we fake it deterministically.
    return f"You asked: {query!r}. The answer is 42."

# Generate 20 fake interactions
for i in range(20):
    answer_question(f"What is question number {i}?")

print("Generated 20 traces.")
```

Run it:

```bash
python my_agent.py
# Generated 20 traces.
```

Each call to `answer_question` was captured as a trace, hashed, and added to the Merkle tree under the `quickstart-demo` workspace.

## Step 4 — Generate an attestation

```bash
vidimus attest --workspace quickstart-demo --output report.json
```

You'll see output like:

```
Attestation generated:
  Period: 2026-05-15T05:42:01Z → 2026-05-15T05:42:03Z
  Traces: 20
  Merkle root: 9c4e7b3a...
  Signed by: 4a8d2f... (default)
  Saved to: report.json
```

Open `report.json` in your editor. It's a single self-contained JSON file containing:

- The Merkle root over all 20 traces
- The list of trace IDs and their leaf hashes
- The Ed25519 signature
- The public-key fingerprint of the issuer

## Step 5 — Verify offline

Now imagine you send `report.json` to a third party — a compliance officer, an auditor, a customer. They don't have access to your traces, your database, or your private key. They just have the file.

```bash
vidimus verify report.json
# ✓ Schema valid (vidimus.attestation.v1)
# ✓ Merkle root recomputed: 9c4e7b3a... matches
# ✓ Ed25519 signature valid (key fingerprint: 4a8d2f...)
# ✓ Verification: PASS
```

Verification is **entirely offline**. The `verify` command never contacts a server.

## Step 6 — Prove tampering is detected

Open `report.json` and change one byte — for example, modify `"trace_count": 20` to `"trace_count": 21`. Save.

```bash
vidimus verify report.json
# ✗ Ed25519 signature INVALID
# ✗ Verification: FAIL
```

Any modification — even one byte — invalidates the signature. This is the core property of the attestation.

Restore the file (or regenerate with `vidimus attest`) before continuing.

## Step 7 — Inspect with `--verbose`

```bash
vidimus verify report.json --verbose
```

This prints every check performed, including:

- Canonical JSON computation
- Merkle tree reconstruction (you can see each leaf hash)
- Public-key resolution
- Signature verification

It's the equivalent of `git fsck` for your attestation.

## What you just demonstrated

A self-contained, cryptographically signed audit trail of your agent's behavior, verifiable by any third party offline, using only open primitives (Ed25519, SHA-256, RFC 8785 canonical JSON).

## Next steps

- **Add calibrated metrics.** See [examples/basic_agent.py](../examples/basic_agent.py) for a walkthrough that includes multi-judge evaluation with bootstrap CI.
- **Integrate with Opik.** See [examples/opik_integration.py](../examples/opik_integration.py).
- **Integrate with LangChain.** See [examples/langchain_integration.py](../examples/langchain_integration.py).
- **Anchor on-chain.** See [ARCHITECTURE.md §7](../ARCHITECTURE.md) and [contracts/](../contracts/).
- **Read the threat model.** See [ARCHITECTURE.md §11](../ARCHITECTURE.md).

## Common questions

**Q: Can I use my own KMS-managed key?**
Yes — `vidimus keys import-kms` is on the v0.2 roadmap. For now, local keys with mode 0600 file permissions are the only supported option.

**Q: Does this work with my existing Opik / Langfuse setup?**
Yes. Vidimus consumes OpenTelemetry spans, so any tool that exports OTel can feed Vidimus in parallel. See the integration examples.

**Q: Where are the traces stored?**
By default, in an in-memory store that loses data when the process exits. Persistent DuckDB storage is on the v0.2 roadmap. For now, the workflow is: instrument → run → attest immediately → save the report.

**Q: Is this production-ready?**
**No.** Vidimus is in alpha. Cryptographic primitives are stable (and will not break), but the SDK surface may change and persistent storage is not yet implemented. Use it to prototype, generate proofs-of-concept, and give feedback. Do not rely on it for compliance evidence in production until v1.0.
