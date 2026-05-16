"""Tests for the real LLM judge implementations.

These tests mock the SDK clients so they run in CI without API keys. They
verify:
  - The judge classes can be constructed with the lazy import pattern.
  - The response parser handles strict JSON, regex fallback, and bad inputs.
  - Retry logic kicks in on transient errors.
  - The factory builds the right judge type from an identifier string.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from vidimus.audit.judges import (
    AnthropicJudge,
    Judge,
    OllamaJudge,
    OpenAIJudge,
    StubJudge,
    _parse_judge_response,
    build_judges,
)
from vidimus.audit.schemas import Trace


def _make_trace(trace_id: str = "t-1") -> Trace:
    return Trace(
        trace_id=trace_id,
        workspace="test-workspace",
        spans=[],
        input="What is the capital of France?",
        output="The capital of France is Paris.",
        model="test-model",
        cost_usd=0.001,
        captured_at=datetime.now(timezone.utc),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Response parser
# ─────────────────────────────────────────────────────────────────────────────


class TestResponseParser:
    def test_strict_json(self):
        assert _parse_judge_response('{"score": 0.85, "rationale": "ok"}', "relevance") == 0.85

    def test_binary_zero(self):
        assert _parse_judge_response('{"score": 0.0, "rationale": "fine"}', "hallucination") == 0.0

    def test_binary_one(self):
        assert _parse_judge_response('{"score": 1.0, "rationale": "bad"}', "hallucination") == 1.0

    def test_clamps_out_of_range(self):
        # Judge returned 1.5; we clamp to 1.0
        assert _parse_judge_response('{"score": 1.5, "rationale": "x"}', "relevance") == 1.0
        assert _parse_judge_response('{"score": -0.2, "rationale": "x"}', "relevance") == 0.0

    def test_markdown_fence_stripped(self):
        raw = '```json\n{"score": 0.5, "rationale": "y"}\n```'
        assert _parse_judge_response(raw, "relevance") == 0.5

    def test_regex_fallback(self):
        raw = 'Here is my evaluation: {"score": 0.7, "rationale": "decent"} as the answer.'
        assert _parse_judge_response(raw, "relevance") == 0.7

    def test_bad_input_raises(self):
        with pytest.raises(ValueError, match="Could not parse"):
            _parse_judge_response("not a valid response", "relevance")

    def test_missing_score_raises(self):
        with pytest.raises(ValueError, match="Could not parse"):
            _parse_judge_response('{"rationale": "missing score"}', "relevance")


# ─────────────────────────────────────────────────────────────────────────────
# Stub judge (no mocking needed)
# ─────────────────────────────────────────────────────────────────────────────


class TestStubJudge:
    def test_deterministic(self):
        trace = _make_trace()
        j = StubJudge(seed="a")
        assert j.score(trace, "halluc") == j.score(trace, "halluc")

    def test_different_seeds_disagree_sometimes(self):
        trace = _make_trace()
        scores = {StubJudge(seed=s).score(trace, "halluc") for s in "abcdefgh"}
        # With 8 different seeds, we should see both 0.0 and 1.0
        assert len(scores) == 2

    def test_continuous_in_range(self):
        trace = _make_trace()
        j = StubJudge(seed="cont", binary=False)
        s = j.score(trace, "relevance")
        assert 0.0 <= s < 1.0


# ─────────────────────────────────────────────────────────────────────────────
# OpenAI judge (mocked)
# ─────────────────────────────────────────────────────────────────────────────


class TestOpenAIJudge:
    def test_import_error_message(self):
        """If openai is not installed, constructor raises a helpful ImportError."""
        with patch.dict("sys.modules", {"openai": None}):
            with pytest.raises(ImportError, match="vidimus\\[openai\\]"):
                OpenAIJudge()

    def test_score_success(self):
        # Build a mock that simulates a successful API call.
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(
            {"score": 0.92, "rationale": "very relevant"}
        )

        with patch("openai.OpenAI") as MockOpenAI:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            MockOpenAI.return_value = mock_client

            judge = OpenAIJudge(api_key="fake-key")
            score = judge.score(_make_trace(), "relevance")
            assert score == 0.92
            assert judge.name == "openai:gpt-4o-mini"

    def test_retry_on_failure(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"score": 0.5, "rationale": "ok"}'

        with patch("openai.OpenAI") as MockOpenAI, patch("time.sleep") as mock_sleep:
            mock_client = MagicMock()
            # Fail twice, then succeed
            mock_client.chat.completions.create.side_effect = [
                Exception("transient"),
                Exception("transient"),
                mock_response,
            ]
            MockOpenAI.return_value = mock_client

            judge = OpenAIJudge(api_key="fake-key", max_retries=3)
            score = judge.score(_make_trace(), "relevance")
            assert score == 0.5
            assert mock_sleep.call_count == 2


# ─────────────────────────────────────────────────────────────────────────────
# Anthropic judge (mocked)
# ─────────────────────────────────────────────────────────────────────────────


class TestAnthropicJudge:
    def test_import_error_message(self):
        with patch.dict("sys.modules", {"anthropic": None}):
            with pytest.raises(ImportError, match="vidimus\\[anthropic\\]"):
                AnthropicJudge()

    def test_score_success(self):
        # Anthropic content is a list of blocks with .text
        mock_block = MagicMock()
        mock_block.text = json.dumps({"score": 0.78, "rationale": "good"})
        mock_response = MagicMock()
        mock_response.content = [mock_block]

        with patch("anthropic.Anthropic") as MockAnthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            MockAnthropic.return_value = mock_client

            judge = AnthropicJudge(api_key="fake-key")
            score = judge.score(_make_trace(), "answer_quality")
            assert score == 0.78
            assert judge.name.startswith("anthropic:")


# ─────────────────────────────────────────────────────────────────────────────
# Ollama judge (mocked)
# ─────────────────────────────────────────────────────────────────────────────


class TestOllamaJudge:
    def test_score_success(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {"content": '{"score": 1.0, "rationale": "hallucinated"}'}
        }
        mock_response.raise_for_status = MagicMock()

        with patch("requests.post", return_value=mock_response) as mock_post:
            judge = OllamaJudge(model="llama3.1:8b")
            score = judge.score(_make_trace(), "hallucination")
            assert score == 1.0
            assert mock_post.called
            assert judge.name == "ollama:llama3.1:8b"


# ─────────────────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────────────────


class TestBuildJudges:
    def test_stub_default(self):
        judges = build_judges(["stub"])
        assert len(judges) == 1
        assert isinstance(judges[0], StubJudge)

    def test_stub_with_seed(self):
        judges = build_judges(["stub:my-seed"])
        assert judges[0].name == "stub:my-seed"

    def test_multiple_stubs(self):
        judges = build_judges(["stub:a", "stub:b", "stub:c"])
        assert len(judges) == 3
        assert {j.name for j in judges} == {"stub:a", "stub:b", "stub:c"}

    def test_openai_identifier(self):
        # We can't actually construct without mocking openai, but we can
        # verify the routing logic raises a specific error type.
        with patch("openai.OpenAI"):
            judges = build_judges(["openai:gpt-4o-mini"])
            assert len(judges) == 1
            assert judges[0].name == "openai:gpt-4o-mini"

    def test_anthropic_identifier(self):
        with patch("anthropic.Anthropic"):
            judges = build_judges(["anthropic:claude-3-5-haiku-20241022"])
            assert judges[0].name == "anthropic:claude-3-5-haiku-20241022"

    def test_ollama_identifier(self):
        judges = build_judges(["ollama:llama3.1:8b"])
        assert judges[0].name == "ollama:llama3.1:8b"

    def test_unknown_identifier_raises(self):
        with pytest.raises(ValueError, match="Unknown judge identifier"):
            build_judges(["mistral:7b"])

    def test_instance_passthrough(self):
        existing = StubJudge(seed="already-built")
        judges = build_judges([existing, "stub:new"])
        assert judges[0] is existing
        assert judges[1].name == "stub:new"

    def test_bad_type_raises(self):
        with pytest.raises(TypeError):
            build_judges([42])  # type: ignore[list-item]


def test_judge_abc_cannot_instantiate():
    with pytest.raises(TypeError):
        Judge()  # type: ignore[abstract]
