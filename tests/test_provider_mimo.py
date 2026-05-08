"""Tests for src/execution/providers/mimo.py."""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import patch

from src.execution.gateway_v2 import build_default_providers, default_gateway
from src.execution.providers.mimo import (
    MiMoProvider,
    _normalize_model_name,
    _resolve_api_key,
    _resolve_base_url,
)


class FakeHTTPResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class TestMiMoConfig:
    def test_resolves_token_plan_env_aliases(self, monkeypatch):
        monkeypatch.delenv("XIAOMI_MIMO_API_KEY", raising=False)
        monkeypatch.setenv("MIMO_API_KEY", "tp-test")
        assert _resolve_api_key() == "tp-test"

    def test_blank_primary_key_falls_through_to_token_plan_alias(self, monkeypatch):
        monkeypatch.setenv("XIAOMI_MIMO_API_KEY", "   ")
        monkeypatch.setenv("MIMO_API_KEY", "tp-test")
        assert _resolve_api_key() == "tp-test"

    def test_blank_mimo_keys_count_as_absent(self, monkeypatch):
        monkeypatch.setenv("XIAOMI_MIMO_API_KEY", "   ")
        monkeypatch.setenv("MIMO_API_KEY", "")
        assert _resolve_api_key() is None
        assert MiMoProvider(prefer_cli=False).offline is True

    def test_default_base_url_uses_official_openai_compatible_api_even_for_tp_keys(self, monkeypatch):
        monkeypatch.delenv("MIMO_BASE_URL", raising=False)
        monkeypatch.delenv("XIAOMI_MIMO_BASE_URL", raising=False)
        assert _resolve_base_url("tp-test") == "https://api.xiaomimimo.com/v1"

    def test_explicit_base_url_override_is_respected(self, monkeypatch):
        monkeypatch.setenv("MIMO_BASE_URL", "https://token-plan-ams.xiaomimimo.com/v1/")
        monkeypatch.delenv("XIAOMI_MIMO_BASE_URL", raising=False)
        assert _resolve_base_url("tp-test") == "https://token-plan-ams.xiaomimimo.com/v1"

    def test_regular_keys_default_to_official_api_base(self, monkeypatch):
        monkeypatch.delenv("MIMO_BASE_URL", raising=False)
        monkeypatch.delenv("XIAOMI_MIMO_BASE_URL", raising=False)
        assert _resolve_base_url("sk-test") == "https://api.xiaomimimo.com/v1"

    def test_model_names_are_lowercase_api_names(self):
        assert _normalize_model_name("MiMo-V2.5-Pro") == "mimo-v2.5-pro"
        assert _normalize_model_name("MiMo-V2.5") == "mimo-v2.5"
        assert _normalize_model_name("xiaomi_mimo/MiMo-V2.5-Pro") == "mimo-v2.5-pro"


class TestMiMoProvider:
    def test_offline_when_no_key(self, monkeypatch):
        monkeypatch.delenv("XIAOMI_MIMO_API_KEY", raising=False)
        monkeypatch.delenv("MIMO_API_KEY", raising=False)
        provider = MiMoProvider(prefer_cli=False)
        assert provider.offline is True
        result = provider.call("test", "hello")
        assert result.provider == "mimo"
        assert "[mock-mimo/test]" in result.text

    def test_chat_completion_uses_official_api_key_header_and_openai_payload(self):
        captured = {}

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["timeout"] = timeout
            captured["headers"] = dict(req.header_items())
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return FakeHTTPResponse(
                {
                    "choices": [{"message": {"content": "MiMo response"}}],
                    "model": "mimo-v2.5-pro",
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                }
            )

        provider = MiMoProvider(
            api_key="tp-secret",
            model="MiMo-V2.5-Pro",
            offline=False,
        )
        with patch("urllib.request.urlopen", fake_urlopen):
            result = provider.call("report", "hello", max_tokens=77, temperature=0.2)

        assert captured["url"] == "https://api.xiaomimimo.com/v1/chat/completions"
        headers = {key.lower(): value for key, value in captured["headers"].items()}
        assert headers["api-key"] == "tp-secret"
        assert headers["content-type"] == "application/json"
        assert captured["body"]["model"] == "mimo-v2.5-pro"
        assert captured["body"]["messages"] == [{"role": "user", "content": "hello"}]
        assert captured["body"]["max_completion_tokens"] == 77
        assert captured["body"]["thinking"] == {"type": "disabled"}
        assert result.text == "MiMo response"
        assert result.provider == "mimo"
        assert result.model == "mimo-v2.5-pro"
        assert result.cost_usd == 0.0

    def test_default_gateway_prioritizes_mimo_when_key_present(self, monkeypatch):
        monkeypatch.setenv("XIAOMI_MIMO_API_KEY", "tp-test")
        monkeypatch.delenv("MUCHANIPO_OFFLINE", raising=False)
        providers = build_default_providers(prefer_cli=False)
        assert providers["mimo"].offline is False
        gateway = default_gateway(providers=providers)
        assert gateway.fallback_chain["report"][0] == "mimo"
        assert gateway.fallback_chain["research"][0] == "mimo"
        assert gateway.stage_routes["report"] == "mimo"

    def test_default_gateway_preserves_explicit_routes_even_when_mimo_key_present(self, monkeypatch):
        monkeypatch.setenv("XIAOMI_MIMO_API_KEY", "tp-test")
        for name in (
            "MUCHANIPO_VERIFICATION_ROUTING",
            "MUCHANIPO_LIVE_VERIFICATION_ROUTING",
            "MUCHANIPO_MODEL_ROUTING",
            "MUCHANIPO_API_ROUTING",
            "MUCHANIPO_EXTERNAL_MODEL_ROUTING",
            "MUCHANIPO_PROVIDER_ROUTING",
        ):
            monkeypatch.delenv(name, raising=False)
        providers = build_default_providers(prefer_cli=False)
        gateway = default_gateway(
            providers=providers,
            routes={"report": "anthropic"},
            fallback_chain={"report": ["anthropic", "mock"]},
        )
        assert gateway.stage_routes["report"] == "anthropic"
        assert gateway.fallback_chain["report"] == ["anthropic", "mock"]
