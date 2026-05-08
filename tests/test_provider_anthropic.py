"""Tests for src/execution/providers/anthropic.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.council.karpathy_prompts import build_chairman_prompt, build_individual_prompt, build_peer_review_prompt
from src.council.parsers import parse_council_response
from src.council.persona_generator import Draft
from src.council.persona_prompts import build_persona_deep_validate_prompt, parse_persona_validation_response
from src.council.round_layers import DEFAULT_LAYERS
from src.evidence.artifact import EvidenceRef
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

    def test_does_not_read_claude_code_oauth_file(self, monkeypatch, tmp_path):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        home = tmp_path / "home"
        settings = home / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text('{"oauthToken":"do-not-read"}', encoding="utf-8")
        monkeypatch.setenv("HOME", str(home))

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

    def test_offline_council_returns_structured_json(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        provider = AnthropicProvider(offline=True, prefer_cli=False)
        layer = DEFAULT_LAYERS[0]
        prompt = build_individual_prompt({"persona_id": "p1", "role": "market_researcher"}, layer)

        result = provider.call("council", prompt, council_stage="individual", layer_id=layer.layer_id)
        parsed = parse_council_response(result.text, layer)

        assert parsed.layer_id == layer.layer_id
        assert "mock-anthropic" not in parsed.key_claim
        assert parsed.body_claims
        assert parsed.evidence_ref_ids[:2] == ["mock-evidence-1", "mock-evidence-2"]
        assert parsed.framework_output["offline_mock"] is True

    def test_offline_chairman_mock_keeps_report_claims_readable(self):
        provider = AnthropicProvider(offline=True, prefer_cli=False)
        layer = DEFAULT_LAYERS[1]
        prompt = build_chairman_prompt({}, {}, layer)

        result = provider.call("council", prompt, council_stage="chairman", layer_id=layer.layer_id)
        parsed = parse_council_response(result.text, layer)

        assert parsed.key_claim.startswith("흐름 검증")
        assert "실제 출처" in parsed.key_claim
        assert "조건부 권고" not in parsed.key_claim
        assert parsed.framework == "Porter 5 Forces"

    def test_offline_chairman_uses_source_backed_evidence_context(self):
        provider = AnthropicProvider(offline=True, prefer_cli=False)
        layer = DEFAULT_LAYERS[1]
        evidence = [
            EvidenceRef(
                id="openalex:W123",
                source_url="https://openalex.org/W123",
                source_title="Plant disease diagnostics competitor pricing market evidence",
                quote="Plant disease diagnostics competitor pricing evidence",
                source_grade="A",
                provenance={"kind": "openalex", "source": "https://openalex.org/W123"},
            )
        ]
        prompt = build_chairman_prompt({}, {}, layer, evidence_refs=evidence)

        result = provider.call("council", prompt, council_stage="chairman", layer_id=layer.layer_id)
        parsed = parse_council_response(result.text, layer)

        assert parsed.evidence_ref_ids == ["openalex:W123"]
        assert "offline 실행" not in "\n".join(parsed.body_claims)
        assert "조건부 권고" not in parsed.key_claim
        assert parsed.framework_output["source_backed"] is True

    def test_offline_peer_review_uses_source_backed_evidence_context(self):
        provider = AnthropicProvider(offline=True, prefer_cli=False)
        layer = DEFAULT_LAYERS[1]
        evidence = [
            EvidenceRef(
                id="crossref-1-1-abcdef1234",
                source_url="https://doi.org/10.1234/strawberry",
                source_title="Strawberry diagnostics competitor pricing evidence",
                quote="Strawberry disease diagnostics competitor pricing evidence",
                source_grade="A",
                provenance={"kind": "crossref", "source": "https://doi.org/10.1234/strawberry"},
            )
        ]
        prompt = build_peer_review_prompt(
            {"persona_id": "p1", "role": "market_researcher"},
            [{"key_claim": "source-backed claim", "body_claims": ["support"]}],
            layer,
            evidence_refs=evidence,
        )

        result = provider.call("council", prompt, council_stage="peer_review", layer_id=layer.layer_id)
        parsed = result.text

        assert "crossref-1-1-abcdef1234" in parsed
        assert "offline mock" not in parsed

    def test_offline_hachimi_validation_mock_preserves_entity_personas(self):
        provider = AnthropicProvider(offline=True, prefer_cli=False)
        draft = Draft(
            persona_id="mirofish-entity-001",
            name="Entity Reviewer",
            role="ontology_reviewer",
            intent="Evaluate ontology-grounded evidence.",
            allowed_tools=["model_gateway"],
            required_outputs=["council_round_response"],
            value_axes={
                "time_horizon": "mid",
                "risk_tolerance": 0.35,
                "stakeholder_priority": ["primary"],
                "innovation_orientation": 0.55,
            },
            manifest={"mirofish_source": "generate_persona_from_entity"},
        )
        prompt = build_persona_deep_validate_prompt(
            draft,
            {"roles": ["ontology_reviewer"], "allowed_tools": ["model_gateway"]},
            "MiroFish validation smoke",
        )

        result = provider.call("council", prompt)
        score, reason, issues = parse_persona_validation_response(result.text)

        assert score >= 0.8
        assert "ontology-grounded personas" in reason
        assert issues == []

    def test_offline_override(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("ANTHROPIC_OFFLINE", "1")
        p = AnthropicProvider()
        assert p.offline is True

    def test_prefer_cli_uses_installed_claude_without_api_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        p = AnthropicProvider(claude_bin="/usr/local/bin/claude", prefer_cli=True)
        assert p.use_cli is True
        assert p.offline is False


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
