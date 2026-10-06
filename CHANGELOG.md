# Changelog

All notable changes to Vidimus will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0a2] — 2026-05-17

Implementation completeness milestone. Every component promised in the README is now backed by working code — no more stubs masquerading as features.

### Added

**Real LLM judges** (`src/vidimus/audit/judges.py`)
- `OpenAIJudge`: GPT-4o / GPT-4 / any OpenAI chat model with structured JSON output, exponential retry, lazy SDK import
- `AnthropicJudge`: Claude Sonnet / Haiku via the Messages API, same retry semantics
- `OllamaJudge`: local OSS models (Llama 3, Mistral, etc.) over HTTP, no API key needed
- Shared judge prompt template for consistent scoring across backends
- Response parser handling strict JSON, markdown-fenced JSON, and regex fallback

**DuckDB persistent storage** (`src/vidimus/storage/duckdb_store.py`)
- Full SQL schema with indexes (traces, merkle_checkpoints)
- Same interface as `InMemoryStore`, drop-in replacement
- Context manager support
- 13 new tests covering CRUD, time-window filtering, checkpoints

**OpenTelemetry HTTP receiver** (`src/vidimus/receivers/otlp.py`)
- FastAPI server listening on port 4318 (OTel standard)
- Full OTLP/JSON parser: resource spans → scope spans → span groups by trace_id
- Health endpoint at `/health`
- Drop-in alongside Opik, Langfuse, LangChain, raw OTel SDK

**On-chain anchoring** (`src/vidimus/audit/anchor.py`)
- `OnchainAnchorer` for EVM chains (BNB, Ethereum, Base, Sepolia, custom)
- web3.py-backed `anchor()` and `verify_anchor()` methods
- Deterministic anchor hash excluding the signature field
- Default RPC URLs for common networks

**New CLI commands**
- `vidimus prove <trace_id> --against report.json` — Merkle inclusion proof
- `vidimus serve --port 4318` — start the OTLP HTTP receiver

**Real integration examples**
- `examples/opik_integration.py` — dual decoration with `@opik.track` + `@vidimus.audit`
- `examples/langchain_integration.py` — LangChain QA chain instrumented with Vidimus
- `examples/rag_production.py` — sentence-transformers + FAISS + Ollama production RAG

**Optional dependency extras** (`pyproject.toml`)
- `vidimus[openai]`, `vidimus[anthropic]`, `vidimus[ollama]`
- `vidimus[duckdb]`, `vidimus[otel]`, `vidimus[onchain]`
- `vidimus[rag]`, `vidimus[all]`

### Changed
- Test count: **68 → 136** passing tests
- All `# TODO v0.2:` markers removed; every promise is now backed by code
- pyproject.toml URLs point to `github.com/kabNath/vidimus`
- Badge configuration in README updated (PyPI placeholder replaced with static version badge)

### Fixed
- `build_judges()` now accepts pre-instantiated `Judge` instances in addition to identifier strings
- OTLP receiver correctly handles empty `parentSpanId` (treats as `None`)

## [0.1.0a1] — 2026-05-15

Initial public alpha release of Module A.

### Added
- RFC 8785 canonical JSON serializer
- RFC 6962 SHA-256 Merkle tree with inclusion proofs
- Ed25519 key generation, signing, and verification
- Bootstrap confidence intervals (vectorized numpy)
- Cohen's kappa, Fleiss's kappa, Krippendorff's alpha
- Pydantic v2 schemas
- Deterministic `StubJudge`
- `attest()` orchestrator and `verify()` with fatal/warning separation
- `@vidimus.audit` decorator and `vidimus.trace()` context manager
- Thread-safe in-memory trace store
- CLI: `init`, `version`, `keys generate|list`, `attest`, `verify`
- `VidimusAnchor.sol` smart contract source
- Docker multi-stage build
- 68 tests, CI workflow

[0.1.0a2]: https://github.com/kabNath/vidimus/compare/v0.1.0a1...v0.1.0a2
[0.1.0a1]: https://github.com/kabNath/vidimus/releases/tag/v0.1.0a1
