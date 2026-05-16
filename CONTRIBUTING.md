# Contributing to Vidimus

Thank you for considering a contribution. Vidimus is in alpha and we welcome help — but we ask that you read this document first, especially the sections on cryptographic review and signed commits.

## Code of conduct

By participating in this project you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md). In short: be kind, assume good faith, no harassment.

## What we particularly want help with

In rough order of impact:

1. **Cryptography review.** The Merkle tree (RFC 6962 convention), Ed25519 signing, and RFC 8785 canonical JSON are the trust foundation. If you spot a deviation from the specs, an unsafe default, or a side-channel concern, please open a security advisory (see [SECURITY.md](SECURITY.md)) rather than a public issue.
2. **Calibration methodology.** The bootstrap CI + multi-judge agreement pattern is opinionated. If you have published or unpublished work on better approaches (Bayesian intervals, judge debiasing, etc.), open a discussion.
3. **OpenTelemetry exporter integrations.** Each LLM tracing tool exports OTel slightly differently. We want clean Vidimus-compatible bridges for Opik, Langfuse, LangSmith, Phoenix, OpenLLMetry, and raw OTel SDKs.
4. **Documentation translation.** French and Mandarin are highest priority.
5. **Issue triage and reproduction.** If you can reproduce a bug report or add a failing test, that is genuinely useful work.

## What we will probably reject

- New top-level features in Module A without a discussion first. The v0.1 surface is intentionally small.
- Adding dependencies. Each new dependency is a supply-chain risk and a maintenance burden. The bar is high.
- Style refactors. We run `ruff` in CI; if it passes, we generally do not want diff churn.
- Performance optimizations without benchmarks demonstrating the improvement.

## Development setup

```bash
git clone https://github.com/vidimus-ai/vidimus.git
cd vidimus
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
pytest
```

## Workflow

1. Open an issue or discussion describing the change you want to make.
2. Wait for a maintainer to acknowledge ("yes, please proceed" or "let's discuss"). We do not want you to invest hours on a PR we cannot merge.
3. Fork, branch, implement.
4. Run `make check` (lint + types + tests). Everything must pass.
5. Open a pull request. The PR template asks for: motivation, summary, breaking changes (if any), how you tested it.
6. A maintainer will review. For security-relevant code, two maintainer approvals are required.
7. We squash-merge.

## Coding standards

- Python 3.10+. We use union syntax `X | Y` and `dict[str, int]` over `Dict[str, int]`.
- Type hints everywhere. `mypy --strict` must pass.
- Public functions and classes have docstrings. Internal helpers should be self-explanatory or have a one-line comment.
- Tests for every new public function. We use `pytest`. Property-based tests via `hypothesis` are welcome for parsers and crypto code.
- No `print()` in library code. Use `logging` or, for the CLI, the existing `rich.Console`.

## Cryptographic and security code

Any change to files under `src/vidimus/audit/` that touches Merkle construction, signing, key handling, or canonical JSON requires:

- An explanation of the change and the threat it addresses or feature it enables.
- Test vectors (input → expected output) for any new code path.
- A note about what the change does *not* protect against.
- Approval from at least two maintainers.

If you find a security issue, **do not open a public issue**. See [SECURITY.md](SECURITY.md).

## DCO sign-off

All commits must be signed off per the [Developer Certificate of Origin](https://developercertificate.org/). Use `git commit -s`. A bot will reject unsigned commits.

We may add a CLA in the future as the project matures; until then DCO is sufficient.

## Licensing

By contributing you agree that your contributions will be licensed under Apache 2.0, matching the rest of the project.

## Questions

Open a discussion on GitHub, or join Discord at https://discord.gg/vidimus.
