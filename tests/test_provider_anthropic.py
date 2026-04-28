"""Tests for src/execution/providers/anthropic.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.execution.providers.anthropic import (
    AnthropicProvider,
    _estimate_cost,
    _fallback_models,
    _resolve_api_key,
)


class FakeMessage:
    def __init__(self, text: str, input_tokens: int = 10, output_tokens: int = 20):
        self.content = [MagicMock(text=text)]
        self.usage = MagicMock(input_tokens=input_tokens, output_tokens=output_tokens)


class FakeStream:
    def __init__(self, chunks: list[str]):
        self._chunks = chunks
        self.current_message_snapshot = MagicMock(
            usage=MagicMock(input_tokens=5, output_tokens=10)
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    @property
    def text_stream(self):
        yield from self._chunks


class TestResolveApiKey:
    def test_env_var_priority(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        assert _resolve_api_key() == "sk-test"

    def test_none_when_missing(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        assert _resolve_api_key() is None


class TestEstimateCost:
    def test_sonnet_pricing(self):
        msg = FakeMessage("hi", input_tokens=1_000_000, output_tokens=1_000_000)
        cost = _estimate_cost("claude-sonnet-4-6", msg)
        # $3 input + $15 output = $18 per 1M each
        assert pytest.approx(cost, 0.001) == 18.0

    def test_haiku_pricing(self):
        msg = FakeMessage("hi", input_tokens=2_000_000, output_tokens=1_000_000)
        cost = _estimate_cost("claude-haiku-4-5", msg)
        # $0.25*2 + $1.25*1 = $1.75
        assert pytest.approx(cost, 0.001) == 1.75


class TestFallbackModels:
    def test_start_from_preferred(self):
        models = _fallback_models("claude-sonnet-4-6")
        assert models[0] == "claude-sonnet-4-6"
        assert "claude-haiku-4-5" in models

    def test_unknown_model_appended(self):
        models = _fallback_models("unknown")
        assert models[0] == "unknown"
        assert "claude-opus-4-7" in models


class TestAnthropicProviderOffline:
    def test_offline_when_no_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        p = AnthropicProvider()
        assert p.offline is True
        result = p.call("test", "hello world")
        assert result.provider == "anthropic"
        assert "[mock-anthropic/test]" in result.text
        assert result.cost_usd == 0.0

    def test_offline_override(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("ANTHROPIC_OFFLINE", "1")
        p = AnthropicProvider()
        assert p.offline is True


class TestAnthropicProviderMockClient:
    def test_basic_call(self):
        client = MagicMock()
        client.messages.create.return_value = FakeMessage("result", 100, 200)
        p = AnthropicProvider(api_key="sk-test", client=client, offline=False)
        result = p.call("stage", "prompt")
        assert result.text == "result"
        assert result.model == "claude-sonnet-4-6"
        assert result.cost_usd > 0

    def test_streaming_call(self):
        client = MagicMock()
        stream = FakeStream(["chunk1", "chunk2"])
        client.messages.stream.return_value = stream
        p = AnthropicProvider(api_key="sk-test", client=client, offline=False)
        chunks: list[str] = []
        result = p.call("stage", "prompt", stream_callback=chunks.append)
        assert result.text == "chunk1chunk2"
        assert chunks == ["chunk1", "chunk2"]

    def test_fallback_on_failure(self):
        client = MagicMock()
        client.messages.create.side_effect = RuntimeError("rate limit")
        p = AnthropicProvider(api_key="sk-test", client=client, offline=False)
        result = p.call("stage", "prompt")
        assert result.is_fallback is True
        assert "rate limit" in (result.fallback_reason or "")

    def test_allow_fallback_false_raises_after_internal_model_chain(self):
        client = MagicMock()
        client.messages.create.side_effect = RuntimeError("rate limit")
        p = AnthropicProvider(api_key="sk-test", client=client, offline=False)

        with pytest.raises(RuntimeError, match="rate limit"):
            p.call("stage", "prompt", allow_fallback=False)

    def test_model_parameter_override(self):
        client = MagicMock()
        client.messages.create.return_value = FakeMessage("ok", 10, 10)
        p = AnthropicProvider(api_key="sk-test", client=client, offline=False)
        p.call("stage", "prompt", model="claude-opus-4-7")
        call_args = client.messages.create.call_args
        assert call_args.kwargs["model"] == "claude-opus-4-7"
