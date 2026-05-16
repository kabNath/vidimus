# Changelog

All notable changes to Vidimus will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- (nothing yet)

### Changed
- (nothing yet)

### Fixed
- (nothing yet)

## [0.1.0a1] — 2026-05-15

Initial public alpha release of Module A (`vidimus.audit`).

### Added
- RFC 8785 canonical JSON serializer (`vidimus.audit.canonical`)
- RFC 6962 SHA-256 Merkle tree with inclusion proofs (`vidimus.audit.merkle`)
- Ed25519 key generation, signing, and verification (`vidimus.audit.keys`, `vidimus.audit.signing`)
- Bootstrap confidence intervals (vectorized numpy)
- Cohen's kappa, Fleiss's kappa, Krippendorff's alpha for multi-judge agreement (`vidimus.audit.uncertainty`)
- Pydantic v2 schemas: `Span`, `Trace`, `CalibratedMetric`, `OnchainAnchor`, `Attestation`
- Deterministic `StubJudge` for development and testing
- `Judge` ABC for plugging in real LLM-as-judge implementations
- `attest()` orchestrator: build Merkle tree, run judges, compute CIs, sign attestation
- `verify()` with separated fatal issues and non-fatal warnings (e.g. low judge agreement)
- `@vidimus.audit` decorator and `vidimus.trace()` context manager
- Thread-safe in-memory trace store (`vidimus.storage.memory.InMemoryStore`)
- CLI: `vidimus init`, `vidimus version`, `vidimus keys generate|list`, `vidimus attest`, `vidimus verify`
- `VidimusAnchor.sol` smart contract for optional EVM on-chain anchoring
- Example: end-to-end agent instrumentation with tamper-detection demo
- Example: integration sketch with Opik
- Example: integration sketch with LangChain via OpenTelemetry
- Quickstart documentation
- 68 unit + end-to-end tests, all passing on CPython 3.11+
- CI workflow: ruff lint + pytest on push and PR

### Known limitations
- Real `OpenAIJudge`, `AnthropicJudge`, `GeminiJudge` implementations are stubs in this release. Use `StubJudge` for now or implement against the `Judge` ABC.
- DuckDB storage backend is planned for v0.2. The in-memory store is suitable for development and short-lived runs only.
- OpenTelemetry HTTP receiver is planned for v0.2.
- The smart contract has not been deployed to mainnet yet; it is provided as source for review.
- Cryptographic primitives have not been externally audited. Treat as experimental.

[Unreleased]: https://github.com/vidimus-ai/vidimus/compare/v0.1.0a1...HEAD
[0.1.0a1]: https://github.com/vidimus-ai/vidimus/releases/tag/v0.1.0a1
