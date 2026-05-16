# Vidimus — Roadmap

Vidimus is a trust stack for the agent lifecycle, shipped as three sequenced modules under one project.

## Module A — `vidimus.audit` 🚧 Alpha

Tamper-evident traces, calibrated uncertainty, cryptographic attestations.

### v0.1.x (current)
- Core primitives: canonical JSON, Merkle trees, Ed25519, bootstrap CI
- StubJudge for development; ABC for real judges
- In-memory storage
- CLI: init, keys, attest, verify
- Smart contract source (not yet deployed)

### v0.2 (Q2 2026)
- DuckDB persistent storage backend
- Real `OpenAIJudge`, `AnthropicJudge`, `GeminiJudge` implementations
- OpenTelemetry HTTP receiver (port 4318)
- Inclusion proof CLI command (`vidimus prove`)
- Smart contract deployed to BNB Chain testnet then mainnet
- `vidimus verify --check-anchor`

### v0.3 (Q3 2026)
- ClickHouse storage tier (opt-in)
- AWS KMS / GCP KMS / Azure Key Vault / HashiCorp Vault integrations
- Documentation site at docs.vidimus.ai
- Stratified sampling for judge runs (cost/confidence knob)
- Encrypted "evidence bundle" mode for attestations that need to include trace contents

### v1.0 (Q4 2026)
- Stable Python API; semver guarantees
- External cryptographic review completed
- Production-grade benchmarks published
- Smart contract deployed to Ethereum, Base, Polygon mainnets

---

## Module B — `vidimus.optimize` 🗓 Q3 2026

DRL-based prompt and agent optimization with the same audit guarantees applied to the optimization process itself.

### Scope
- PPO and MADDPG implementations for prompt optimization, with reward shaping over Vidimus-attested metrics
- Trust-region constraints to bound prompt drift between training rounds
- Every optimization step itself produces a Vidimus attestation, so the *optimization history* is auditable
- Multi-agent scenarios: agents that learn to coordinate, with cryptographic accountability for who-did-what

### Why this module
Existing prompt optimizers (DSPy MIPRO, Opik's "optimizers") use greedy / Bayesian methods. They work for narrow, single-agent settings but break down on multi-agent or long-horizon tasks. DRL is the right tool, but DRL applied to LLMs is fragile without rigorous evaluation infrastructure underneath — which is exactly what Module A provides.

### Tentative milestones
- M0 (Aug 2026): Prototype PPO on single-prompt single-agent task, with v0.2 attestation pipeline
- M1 (Oct 2026): MADDPG on two-agent coordination task
- M2 (Dec 2026): First public benchmark + paper draft
- M3 (Q1 2027): v0.1 release of `vidimus.optimize`

---

## Module C — `vidimus.federate` 🗓 2027

Federated evaluation with secure aggregation and differential privacy, for data that cannot leave its environment.

### Scope
- Run multi-judge evaluations across organizations without trace contents leaving each org's perimeter
- Secure aggregation (multi-party computation) for the metric aggregation step
- Differential privacy guarantees on published cross-org statistics
- Hierarchical Federated Learning (HFL) topology for large deployments

### Why this module
The most valuable LLM evaluations involve sensitive data (medical, financial, legal, personal). Today these orgs cannot share evaluation results because sharing requires exposing the underlying data. Federated evaluation breaks that bind. This module is the highest-difficulty, longest-horizon part of the project and explicitly leverages Nathan's PhD work on HFL-MADRL.

### Tentative milestones
- M0 (Q2 2027): Spec + paper-grade prototype on synthetic data
- M1 (Q3 2027): First two-org pilot with secure aggregation
- M2 (Q4 2027): v0.1 release of `vidimus.federate`

---

## Cross-cutting commitments

These hold across all modules:

- **Apache 2.0 license, no fork-to-paid surprises.** If a feature ships in the OSS repo, it stays in the OSS repo.
- **Reproducibility.** Every benchmark, every claim in marketing material, is reproducible from a public script.
- **No vendor lock-in.** Standard primitives (Ed25519, SHA-256, RFC 8785, OpenTelemetry semconv) only. No custom crypto, no proprietary wire formats.
- **Honest uncertainty.** No point estimates without confidence intervals in any user-facing artifact, ever.

## How to influence the roadmap

- Open a [GitHub Discussion](https://github.com/vidimus-ai/vidimus/discussions) with your use case
- Become a design partner: email **partners@vidimus.ai**
- Contribute code (see [CONTRIBUTING.md](CONTRIBUTING.md))
- Sponsor a specific feature (sustaining sponsors get priority weight on roadmap discussions)

The roadmap is a plan, not a contract. Dates will slip. Priorities will shift in response to user feedback. The order of modules (A → B → C) is firm; the internal milestones are best-effort.
