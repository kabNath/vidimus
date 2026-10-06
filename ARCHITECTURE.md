# Vidimus — Module A Architecture (`vidimus.audit`)

> Tamper-evident traces · Calibrated uncertainty · Cryptographic attestations

This document specifies the technical design of Module A. It is intentionally explicit so that cryptographers, security reviewers, and external contributors can audit the protocol without reading the code.

---

## 1. Design principles

1. **Verifiability without trust.** Any third party must be able to verify a Vidimus attestation offline, given only the attestation file and a public key.
2. **Drop-in.** The user should not have to migrate off Opik, Langfuse, or any existing tool. Vidimus consumes OpenTelemetry spans and emits signed artifacts.
3. **Single binary, no exotic infra.** Default install is `pip install vidimus`. Storage is DuckDB locally; ClickHouse only as an opt-in scale tier.
4. **Honest uncertainty.** Every published metric carries a confidence interval and a multi-judge agreement statistic. Point estimates without calibration are considered a bug.
5. **Open primitives only.** Ed25519 signatures, SHA-256 Merkle trees, RFC 8785 canonical JSON. No proprietary crypto, no unaudited curves.

---

## 2. Core concepts

### 2.1 Trace

A trace is a single agent interaction. It contains spans, inputs, outputs, metadata, and timestamps. Vidimus ingests traces from any OpenTelemetry-compatible source.

### 2.2 Merkle trace store

Traces are hashed and inserted as leaves into a Merkle tree. The current root is published periodically (every N traces, every M minutes, or on demand). Any post-hoc modification to a stored trace invalidates the root, which is signed.

### 2.3 Calibrated metric

A `CalibratedMetric` is never a bare number. It is a tuple containing the point estimate, a bootstrap confidence interval, the number of samples it was computed on, the number and identity of the judges used (for LLM-as-judge metrics), and a multi-judge agreement coefficient (Cohen's κ or Krippendorff's α).

### 2.4 Attestation

An attestation is a signed JSON artifact bundling: a set of trace hashes, a Merkle root, one or more calibrated metrics over those traces, a timestamp, an issuer identity (Ed25519 public key fingerprint), an Ed25519 signature, and an optional on-chain anchor reference.

---

## 3. Pydantic schemas

All Vidimus data structures are typed via Pydantic v2 and serialized to canonical JSON (RFC 8785) before hashing or signing.

```python
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Literal

class Span(BaseModel):
    span_id: str
    parent_span_id: str | None
    name: str
    start_ns: int
    end_ns: int
    attributes: dict[str, str | int | float | bool]
    status: Literal["ok", "error", "unset"]

class Trace(BaseModel):
    trace_id: str
    workspace: str
    spans: list[Span]
    input: str | dict
    output: str | dict
    model: str | None
    cost_usd: float | None
    captured_at: datetime

class CalibratedMetric(BaseModel):
    name: str                          # e.g. "hallucination_rate"
    point_estimate: float
    ci_low: float                      # 95% bootstrap lower bound
    ci_high: float                     # 95% bootstrap upper bound
    n: int                             # sample size
    method: Literal["llm_judge", "heuristic", "human"]
    judges: list[str] = Field(default_factory=list)
    judge_agreement: float | None      # κ or α
    bootstrap_iterations: int = 1000

class Attestation(BaseModel):
    version: Literal["vidimus.attestation.v1"] = "vidimus.attestation.v1"
    workspace: str
    issued_at: datetime
    period_start: datetime
    period_end: datetime
    merkle_root: str                   # hex-encoded SHA-256
    trace_count: int
    metrics: list[CalibratedMetric]
    issuer_pubkey_fingerprint: str     # SHA-256 of Ed25519 public key
    onchain_anchor: OnchainAnchor | None
    signature: str                     # hex-encoded Ed25519 signature
```

The `signature` field is computed over the canonical JSON serialization of the attestation *with the signature field omitted*. This is the standard detached-signature pattern.

---

## 4. Merkle tree

### 4.1 Construction

- Leaves: `SHA-256(canonical_json(trace))` for each trace, sorted by `trace_id`.
- Internal nodes: `SHA-256(left || right)`.
- Odd levels are handled by duplicating the last node (RFC 6962 §2.1 convention, identical to Certificate Transparency).

### 4.2 Storage

Traces and Merkle metadata live in DuckDB (default) or ClickHouse (scale tier).

```sql
CREATE TABLE traces (
    trace_id            TEXT PRIMARY KEY,
    workspace           TEXT NOT NULL,
    canonical_json      BLOB NOT NULL,
    leaf_hash           BLOB NOT NULL,       -- SHA-256 of canonical_json
    captured_at         TIMESTAMP NOT NULL,
    indexed_at          TIMESTAMP NOT NULL
);

CREATE INDEX idx_traces_workspace_captured ON traces (workspace, captured_at);

CREATE TABLE merkle_checkpoints (
    workspace           TEXT NOT NULL,
    root                BLOB NOT NULL,
    trace_count         BIGINT NOT NULL,
    period_start        TIMESTAMP NOT NULL,
    period_end          TIMESTAMP NOT NULL,
    issued_at           TIMESTAMP NOT NULL,
    PRIMARY KEY (workspace, issued_at)
);
```

### 4.3 Inclusion proofs

Every individual trace can be proven to belong to a published root via an O(log n) inclusion proof (standard Merkle path). The CLI exposes this:

```bash
vidimus prove <trace_id> --against report.json
# returns the inclusion path + verification result
```

---

## 5. Signing

### 5.1 Algorithm

Ed25519 (RFC 8032). Chosen for: small keys (32 B), small signatures (64 B), no parameter selection footguns (no curve choice, no nonce reuse risk), constant-time implementations in `pynacl` and `cryptography`.

### 5.2 Key management

- **Local development.** Keys generated and stored in `~/.vidimus/keys/` with file permissions 0600.
- **Production.** Keys backed by AWS KMS, Google Cloud KMS, Azure Key Vault, or HashiCorp Vault. Vidimus never sees the private key; signing is done via the KMS asymmetric sign API.
- **Key rotation.** Old public keys remain valid for verifying past attestations. New attestations use the current key. A `keys.txt` file in the repo (or workspace) maps fingerprints to public keys with validity periods.

### 5.3 What is signed

The canonical JSON (RFC 8785) of the `Attestation` object with `signature` set to the empty string. This is well-defined, deterministic, and verifiable without a custom hashing protocol.

---

## 6. Calibrated uncertainty

### 6.1 Bootstrap confidence intervals

For any metric computed as an aggregate over a set of traces (rate, mean, etc.), Vidimus computes the 95% confidence interval by non-parametric bootstrap:

1. Resample the trace set with replacement, B times (default B = 1000).
2. Compute the metric on each resample.
3. Report the 2.5th and 97.5th percentiles of the bootstrap distribution as the CI.

This makes no parametric assumptions and works for any metric that is a function of the underlying traces.

### 6.2 Multi-judge aggregation

For LLM-as-judge metrics, Vidimus runs the judgment with at least three different judges by default. Configurable models include any combination of OpenAI, Anthropic, Google, Mistral, and open-weight models via Ollama.

Aggregation is the majority vote for categorical judgments, the median for ordinal judgments. The reported `judge_agreement` is:

- **Cohen's κ** when two judges are used (deprecated, only for benchmarking against legacy setups).
- **Fleiss's κ** when three or more judges are used with categorical labels.
- **Krippendorff's α** when judges produce ordinal or continuous outputs.

If `judge_agreement < 0.4`, Vidimus emits a warning in the attestation that the metric should be treated as low-confidence regardless of the CI width. This is a deliberate, opinionated safety net against the well-known reliability problems of LLM-as-judge (Zheng et al. 2023; Panickssery et al. 2024).

### 6.3 Why this matters

A point estimate of "hallucination rate: 3.2%" tells you nothing about whether the next batch of 100 calls will see 0.5% or 8%. The CI does. A score from a single judge that has a known self-preference bias is unreliable; agreement across judges with different families (e.g. Claude + Gemini + Llama) is the only honest signal.

---

## 7. On-chain anchoring (optional)

Anchoring is optional, off by default, and never required for verification. Its purpose is to make the *existence* and *timing* of an attestation publicly verifiable, so that the issuer cannot retroactively claim a different state of affairs.

### 7.1 What gets anchored

Only the Merkle root and a SHA-256 of the attestation file. Never trace contents. Never PII. The anchor is `keccak256(merkle_root || attestation_hash || timestamp)`.

### 7.2 Smart contract

A minimal solidity contract on any EVM-compatible chain:

```solidity
// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.20;

contract VidimusAnchor {
    event Anchored(
        address indexed issuer,
        bytes32 indexed workspaceId,
        bytes32 anchorHash,
        uint64 timestamp
    );

    function anchor(bytes32 workspaceId, bytes32 anchorHash) external {
        emit Anchored(msg.sender, workspaceId, anchorHash, uint64(block.timestamp));
    }
}
```

The contract is deliberately minimal: it emits an event and nothing else. No storage, no upgradability, no admin. Gas cost is ~25k per anchor (BNB Chain: ~$0.005 at typical gas prices).

### 7.3 Default deployments

We will deploy the contract on BNB Chain mainnet, Ethereum mainnet, and Base mainnet. Verifying a CLI command:

```bash
vidimus verify report.json --check-anchor
# fetches the Anchored event from the indicated chain and confirms it matches
```

Users are free to deploy the contract themselves on any other chain.

### 7.4 Why this isn't a blockchain gimmick

The anchor adds no cryptographic strength to the attestation itself — the Ed25519 signature is already unforgeable. What the anchor adds is *non-repudiable timestamping*: the issuer cannot later claim "I produced this report before discovering the bug" if the on-chain anchor predates the discovery. For some users (regulators, public benchmark organizers, fund LPs), that property is worth a dollar.

---

## 8. SDK surface

### 8.1 Decorator

```python
import vidimus

vidimus.init(workspace="acme-prod", judges=["gpt-4o", "claude-sonnet-4", "llama-3-70b"])

@vidimus.audit(metrics=["hallucination", "answer_relevance"])
def my_agent(query: str) -> str:
    return llm.invoke(query)
```

### 8.2 Manual span injection

```python
with vidimus.trace(name="my_agent_call") as t:
    t.set_input(query)
    response = llm.invoke(query)
    t.set_output(response)
    t.set_metadata(model="gpt-4o", cost_usd=0.012)
```

### 8.3 OpenTelemetry passthrough

```python
from opentelemetry import trace as otel_trace
import vidimus

vidimus.install_otel_processor()  # registers a BatchSpanProcessor
# now any OTel-instrumented library (Langchain, LlamaIndex, etc.) flows into Vidimus
```

### 8.4 Attestation generation

```python
attestation = vidimus.attest(
    workspace="acme-prod",
    period_start="2026-05-14T00:00:00Z",
    period_end="2026-05-15T00:00:00Z",
    metrics=["hallucination", "answer_relevance"],
    anchor_to="bnb-chain"  # or None
)
attestation.save("report.json")
```

### 8.5 CLI

```bash
vidimus init                                  # interactive setup
vidimus attest --since 24h --output r.json    # generate signed attestation
vidimus verify r.json                         # offline verification
vidimus verify r.json --check-anchor          # also verify on-chain anchor
vidimus prove <trace_id> --against r.json     # produce inclusion proof
vidimus keys generate                         # local key pair
vidimus keys import-kms <kms-uri>             # delegate signing to KMS
```

---

## 9. OpenTelemetry integration

Vidimus exposes a `OTLPHttpReceiver` that listens on `0.0.0.0:4318` (default OTel HTTP port) and ingests spans directly. This means:

- Anything that already exports to OTel (Opik via its OTel exporter, Langfuse via its OTel mode, OpenLLMetry, raw OpenTelemetry SDK, etc.) can fan out to Vidimus with one config line.
- Vidimus never requires the user to abandon their existing observability stack. It runs alongside.

Span attributes follow the OpenTelemetry Semantic Conventions for Generative AI (currently in `gen_ai.*` namespace) where applicable, with `vidimus.*` extensions for fields that have no official semconv equivalent (e.g. `vidimus.judge_agreement`).

---

## 10. Storage tiers

| Tier | Engine | Use case | Notes |
|---|---|---|---|
| Default | DuckDB | Single-node, up to ~1M traces | Embedded, zero setup, file-based |
| Scale | ClickHouse | Multi-node, 100M+ traces | Optional, opt-in via config |
| Archive | S3 / R2 / GCS | Cold attestations | Object storage of signed JSON only |

The schema is identical across tiers. Migration is a one-shot `COPY` job.

---

## 11. Threat model

What Vidimus protects against:

- **Post-hoc trace tampering.** Detected by Merkle root mismatch.
- **Forged attestations.** Detected by signature verification.
- **Backdated attestations.** Detected by on-chain anchor timestamp.
- **Cherry-picked metric reporting.** Mitigated by mandatory CI + judge agreement disclosure.

What Vidimus does *not* protect against (out of scope for Module A):

- **Compromised signing keys.** Mitigated by KMS-backed keys and rotation, but a leaked private key allows forging new attestations until rotation. The historical record on-chain remains intact.
- **Malicious agent at trace-creation time.** If the agent itself is compromised before logging, Vidimus faithfully signs the compromised behavior. This is by design — Vidimus is a trust layer over what was observed, not a guarantee of agent honesty.
- **Side-channel deanonymization of trace contents.** Workspaces handling PII should redact at the source. Vidimus does not currently provide a redaction primitive; this is on the roadmap.

---

## 12. Performance targets (v0.1)

- Trace ingestion: ≥ 5,000 traces/second on a single 4-core node (DuckDB tier)
- Merkle checkpoint: < 200 ms for 100k traces
- Attestation generation: < 1 second for 10k traces, 3 judges
- Verification: < 100 ms for any attestation, offline, on commodity hardware

These targets are realistic for the design above. v1.0 will publish actual benchmark numbers with reproducible scripts.

---

## 13. Open questions and design tensions

1. **Bootstrap is computationally expensive on large trace sets.** For n > 100k, consider analytic CI (Wald, Wilson) as an optional fast path. Will benchmark in v0.2.
2. **Multi-judge cost.** Three frontier-model judges per metric is expensive. We will support sampling (e.g., judge only a stratified 10% of traces) with explicit CI widening. The cost vs. confidence tradeoff is documented but the user decides.
3. **Privacy of trace contents in attestation reports.** Attestations include trace hashes but not contents. A separate "evidence bundle" mode (opt-in, encrypted) is on the roadmap for cases where the verifier needs to see the underlying traces.
4. **Smart contract upgradability.** Current design is non-upgradable for trust reasons. If a bug is found, we deploy a v2 contract and document the migration. Trade-off is intentional.

Contributions on any of these are welcome via GitHub Discussions.
