"""LLM judge interface and reference implementations.

A judge takes a trace and returns a numerical or categorical score for a
named metric. Multiple judges are run in parallel and their outputs are
aggregated with an agreement coefficient (see ``uncertainty.py``).

v0.1 ships a deterministic ``StubJudge`` for development and testing.
Real judges (OpenAI, Anthropic, Gemini) are stubbed and will land in
v0.2. The interface is stable; only the implementations are TODO.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod

from vidimus.audit.schemas import Trace


class Judge(ABC):
    """Abstract base class for evaluation judges."""

    name: str

    @abstractmethod
    def score(self, trace: Trace, metric: str) -> float:
        """Return a numeric score for ``metric`` on the given trace.

        Conventions:
          - For binary classification metrics (e.g. hallucination), return
            0.0 (negative) or 1.0 (positive).
          - For continuous metrics (e.g. relevance), return a value in [0, 1].
          - For categorical metrics, return the category as an int and
            cast to float.
        """
        raise NotImplementedError


class StubJudge(Judge):
    """Deterministic pseudo-random judge for development and tests.

    Scores are derived from a SHA-256 hash of (judge_seed, trace_id, metric).
    This makes them reproducible, distinct across "judges" (different seeds),
    and not actually random. Useful for:

      - Local development without spending API credits.
      - Reproducible test suites.
      - Sanity-checking the multi-judge aggregation logic.

    Do NOT use this in production. Real evaluation requires real judges.
    """

    def __init__(self, seed: str = "stub-0", binary: bool = True):
        """
        Args:
            seed: A string identifier that varies the judge's outputs.
                Different seeds simulate different judges.
            binary: If True, output 0.0 or 1.0. If False, output [0, 1].
        """
        self.name = f"stub:{seed}"
        self._seed = seed
        self._binary = binary

    def score(self, trace: Trace, metric: str) -> float:
        key = f"{self._seed}|{trace.trace_id}|{metric}".encode()
        h = hashlib.sha256(key).digest()
        # Use first 8 bytes as a uint64 -> float in [0, 1).
        n = int.from_bytes(h[:8], "big")
        x = n / (1 << 64)
        if self._binary:
            return 1.0 if x > 0.5 else 0.0
        return x


# TODO(v0.2): Real LLM judges. The interface is below as a stub.
#
# class OpenAIJudge(Judge):
#     def __init__(self, model: str = "gpt-4o", api_key: str | None = None): ...
#     def score(self, trace: Trace, metric: str) -> float: ...
#
# class AnthropicJudge(Judge):
#     def __init__(self, model: str = "claude-sonnet-4", api_key: str | None = None): ...
#
# class GeminiJudge(Judge):
#     def __init__(self, model: str = "gemini-2.0-flash", api_key: str | None = None): ...


def build_judges(identifiers: list[str]) -> list[Judge]:
    """Construct judge instances from string identifiers.

    Identifiers:
      - ``"stub"`` or ``"stub:<seed>"`` -> StubJudge
      - ``"openai:<model>"``            -> NotImplementedError (v0.2)
      - ``"anthropic:<model>"``         -> NotImplementedError (v0.2)
      - ``"gemini:<model>"``            -> NotImplementedError (v0.2)
    """
    judges: list[Judge] = []
    for ident in identifiers:
        if ident == "stub" or ident.startswith("stub:"):
            seed = ident.split(":", 1)[1] if ":" in ident else "stub-0"
            judges.append(StubJudge(seed=seed))
        elif ident.startswith(("openai:", "anthropic:", "gemini:")):
            raise NotImplementedError(
                f"Judge '{ident}' will land in vidimus v0.2. "
                f"For now use 'stub:<seed>' identifiers."
            )
        else:
            raise ValueError(f"Unknown judge identifier: {ident}")
    return judges
