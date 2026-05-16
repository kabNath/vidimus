"""LLM judge interface and reference implementations.

A judge takes a trace and returns a numerical or categorical score for a
named metric. Multiple judges are run in parallel and their outputs are
aggregated with an agreement coefficient (see ``uncertainty.py``).

This module ships four judge backends:

- ``StubJudge``:      deterministic hash-based judge for tests and CI.
- ``OpenAIJudge``:    real OpenAI Chat Completions judge (GPT-4o, etc.).
- ``AnthropicJudge``: real Anthropic Messages judge (Claude, etc.).
- ``OllamaJudge``:    local OSS judge over the Ollama HTTP API (Llama, etc.).

All real judges share the same prompt template and structured-output protocol.
Each one is independently optional: the corresponding SDK is imported lazily
inside the constructor, so the core ``vidimus`` install does not require
``openai``, ``anthropic``, or any LLM SDK. Install the relevant extra:

    pip install vidimus[openai]      # adds the openai SDK
    pip install vidimus[anthropic]   # adds the anthropic SDK
    pip install vidimus[all]         # everything
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from abc import ABC, abstractmethod
from typing import Any

from vidimus.audit.schemas import Trace

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Abstract interface
# ─────────────────────────────────────────────────────────────────────────────


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
        """
        raise NotImplementedError


# ─────────────────────────────────────────────────────────────────────────────
# Stub judge (deterministic, no network, no cost)
# ─────────────────────────────────────────────────────────────────────────────


class StubJudge(Judge):
    """Deterministic pseudo-random judge for development and tests.

    Scores are derived from a SHA-256 hash of (judge_seed, trace_id, metric).
    Reproducible, distinct across "judges" (different seeds), and not actually
    random. Useful for local dev, reproducible tests, and CI without API keys.
    """

    def __init__(self, seed: str = "stub-0", binary: bool = True):
        self.name = f"stub:{seed}"
        self._seed = seed
        self._binary = binary

    def score(self, trace: Trace, metric: str) -> float:
        key = f"{self._seed}|{trace.trace_id}|{metric}".encode()
        h = hashlib.sha256(key).digest()
        n = int.from_bytes(h[:8], "big")
        x = n / (1 << 64)
        if self._binary:
            return 1.0 if x > 0.5 else 0.0
        return x


# ─────────────────────────────────────────────────────────────────────────────
# Shared prompt template for real LLM judges
# ─────────────────────────────────────────────────────────────────────────────


JUDGE_SYSTEM_PROMPT = """You are an impartial LLM-as-judge evaluator.

You will be given a single AI-system trace consisting of an input and an output.
You must score the output on a specific metric.

Respond ONLY with a single line of JSON in this exact format:
{"score": <number>, "rationale": "<one short sentence>"}

Score conventions:
- For binary metrics (e.g. "hallucination", "toxicity"): score is 0.0 (clean)
  or 1.0 (problematic).
- For continuous metrics (e.g. "relevance", "answer_quality"): score is a real
  number between 0.0 and 1.0, inclusive.

Do not output anything other than the single JSON line."""


JUDGE_USER_TEMPLATE = """Metric to evaluate: {metric}

Trace input:
{input}

Trace output:
{output}

Score this output on the "{metric}" metric. Respond with the JSON line only."""


_JSON_LINE_RE = re.compile(r"\{[^{}]*\"score\"[^{}]*\}")


def _parse_judge_response(raw: str, metric: str) -> float:
    """Parse a judge model's response into a [0, 1] float."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:].lstrip()

    try:
        obj = json.loads(raw)
        score = float(obj["score"])
        return max(0.0, min(1.0, score))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        pass

    m = _JSON_LINE_RE.search(raw)
    if m:
        try:
            obj = json.loads(m.group(0))
            score = float(obj["score"])
            return max(0.0, min(1.0, score))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass

    raise ValueError(f"Could not parse judge response for metric '{metric}': {raw!r}")


def _format_trace_for_judge(trace: Trace) -> tuple[str, str]:
    """Render a Trace into (input_text, output_text) for the prompt."""
    inp = trace.input if isinstance(trace.input, str) else json.dumps(trace.input, default=str)
    out = trace.output if isinstance(trace.output, str) else json.dumps(trace.output, default=str)
    return inp[:4000], out[:4000]


# ─────────────────────────────────────────────────────────────────────────────
# OpenAI judge
# ─────────────────────────────────────────────────────────────────────────────


class OpenAIJudge(Judge):
    """LLM-as-judge backed by the OpenAI Chat Completions API.

    Requires ``pip install vidimus[openai]``.

    Args:
        model: Any OpenAI chat model (default ``gpt-4o-mini``).
        api_key: API key. Defaults to ``OPENAI_API_KEY`` env var.
        timeout: Per-request timeout in seconds.
        max_retries: How many times to retry on transient errors.
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
    ):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ImportError(
                "OpenAIJudge requires the 'openai' package. "
                "Install with: pip install vidimus[openai]"
            ) from exc

        self.name = f"openai:{model}"
        self._model = model
        self._timeout = timeout
        self._max_retries = max_retries
        self._client = OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))

    def score(self, trace: Trace, metric: str) -> float:
        inp, out = _format_trace_for_judge(trace)
        user_prompt = JUDGE_USER_TEMPLATE.format(metric=metric, input=inp, output=out)

        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                resp = self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.0,
                    max_tokens=200,
                    response_format={"type": "json_object"},
                    timeout=self._timeout,
                )
                raw = resp.choices[0].message.content or ""
                return _parse_judge_response(raw, metric)
            except Exception as exc:
                last_exc = exc
                wait = 2**attempt
                logger.warning(
                    "OpenAIJudge attempt %d/%d failed: %s; retrying in %ds",
                    attempt + 1,
                    self._max_retries,
                    exc,
                    wait,
                )
                time.sleep(wait)

        raise RuntimeError(f"OpenAIJudge exhausted retries: {last_exc}")


# ─────────────────────────────────────────────────────────────────────────────
# Anthropic judge
# ─────────────────────────────────────────────────────────────────────────────


class AnthropicJudge(Judge):
    """LLM-as-judge backed by the Anthropic Messages API (Claude).

    Requires ``pip install vidimus[anthropic]``.
    """

    def __init__(
        self,
        model: str = "claude-3-5-haiku-20241022",
        api_key: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
    ):
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise ImportError(
                "AnthropicJudge requires the 'anthropic' package. "
                "Install with: pip install vidimus[anthropic]"
            ) from exc

        self.name = f"anthropic:{model}"
        self._model = model
        self._timeout = timeout
        self._max_retries = max_retries
        self._client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    def score(self, trace: Trace, metric: str) -> float:
        inp, out = _format_trace_for_judge(trace)
        user_prompt = JUDGE_USER_TEMPLATE.format(metric=metric, input=inp, output=out)

        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                resp = self._client.messages.create(
                    model=self._model,
                    max_tokens=200,
                    temperature=0.0,
                    system=JUDGE_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_prompt}],
                    timeout=self._timeout,
                )
                raw = ""
                for block in resp.content:
                    if hasattr(block, "text"):
                        raw += block.text
                return _parse_judge_response(raw, metric)
            except Exception as exc:
                last_exc = exc
                wait = 2**attempt
                logger.warning(
                    "AnthropicJudge attempt %d/%d failed: %s; retrying in %ds",
                    attempt + 1,
                    self._max_retries,
                    exc,
                    wait,
                )
                time.sleep(wait)

        raise RuntimeError(f"AnthropicJudge exhausted retries: {last_exc}")


# ─────────────────────────────────────────────────────────────────────────────
# Ollama judge (local OSS models, no API key needed)
# ─────────────────────────────────────────────────────────────────────────────


class OllamaJudge(Judge):
    """LLM-as-judge backed by a local Ollama server.

    Ollama (https://ollama.com) runs open-weight models locally. No API key,
    no data leaves the user's machine. Requires the model to be pulled:

        ollama pull llama3.1:8b
    """

    def __init__(
        self,
        model: str = "llama3.1:8b",
        base_url: str = "http://localhost:11434",
        timeout: float = 60.0,
        max_retries: int = 2,
    ):
        try:
            import requests
        except ImportError as exc:
            raise ImportError(
                "OllamaJudge requires the 'requests' package. Install with: pip install requests"
            ) from exc

        self.name = f"ollama:{model}"
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._requests = requests

    def score(self, trace: Trace, metric: str) -> float:
        inp, out = _format_trace_for_judge(trace)
        user_prompt = JUDGE_USER_TEMPLATE.format(metric=metric, input=inp, output=out)

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.0, "num_predict": 200},
        }

        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                r = self._requests.post(
                    f"{self._base_url}/api/chat",
                    json=payload,
                    timeout=self._timeout,
                )
                r.raise_for_status()
                data = r.json()
                raw = data.get("message", {}).get("content", "")
                return _parse_judge_response(raw, metric)
            except Exception as exc:
                last_exc = exc
                wait = 2**attempt
                logger.warning(
                    "OllamaJudge attempt %d/%d failed: %s; retrying in %ds",
                    attempt + 1,
                    self._max_retries,
                    exc,
                    wait,
                )
                time.sleep(wait)

        raise RuntimeError(f"OllamaJudge exhausted retries: {last_exc}")


# ─────────────────────────────────────────────────────────────────────────────
# Identifier-based factory
# ─────────────────────────────────────────────────────────────────────────────


def build_judges(identifiers: list[Any]) -> list[Judge]:
    """Construct judge instances from string identifiers or pre-built judges.

    Identifiers:
      - ``"stub"`` or ``"stub:<seed>"``  -> StubJudge
      - ``"openai:<model>"``             -> OpenAIJudge
      - ``"anthropic:<model>"``          -> AnthropicJudge
      - ``"ollama:<model>"``             -> OllamaJudge
      - A ``Judge`` instance             -> returned as-is
    """
    judges: list[Judge] = []
    for ident in identifiers:
        if isinstance(ident, Judge):
            judges.append(ident)
            continue
        if not isinstance(ident, str):
            raise TypeError(f"Judge identifier must be str or Judge, got {type(ident).__name__}")

        if ident == "stub" or ident.startswith("stub:"):
            seed = ident.split(":", 1)[1] if ":" in ident else "stub-0"
            judges.append(StubJudge(seed=seed))
        elif ident.startswith("openai:"):
            judges.append(OpenAIJudge(model=ident.split(":", 1)[1]))
        elif ident.startswith("anthropic:"):
            judges.append(AnthropicJudge(model=ident.split(":", 1)[1]))
        elif ident.startswith("ollama:"):
            judges.append(OllamaJudge(model=ident.split(":", 1)[1]))
        else:
            raise ValueError(
                f"Unknown judge identifier: {ident!r}. "
                f"Expected 'stub[:seed]', 'openai:<model>', 'anthropic:<model>', or 'ollama:<model>'."
            )
    return judges
