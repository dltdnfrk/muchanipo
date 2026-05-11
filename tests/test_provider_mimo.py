import json

from src.execution.providers.mimo import MiMoProvider
from src.execution.providers import mimo


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(
            {
                "model": "mimo-v2.5-pro",
                "choices": [{"message": {"content": "ok"}}],
            }
        ).encode("utf-8")


def test_mimo_uses_documented_api_model_id(monkeypatch):
    provider = MiMoProvider(model="MiMo-V2.5-Pro", api_key="tp-test", base_url="https://token-plan-sgp.xiaomimimo.com/v1", offline=False)

    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["body"] = json.loads(req.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = provider.call("research", "hello", max_tokens=12)

    assert captured["url"] == "https://token-plan-sgp.xiaomimimo.com/v1/chat/completions"
    assert captured["body"]["model"] == "mimo-v2.5-pro"
    assert captured["body"]["max_tokens"] == 12
    assert "max_completion_tokens" not in captured["body"]
    assert captured["body"]["thinking"] == {"disabled": True}
    assert captured["headers"]["Authorization"] == "Bearer tp-test"
    assert captured["headers"].get("Api-key") == "tp-test"
    assert result.text == "ok"
    assert result.model == "mimo-v2.5-pro"


def test_mimo_strips_provider_prefix_and_normalizes_to_api_model_id():
    provider = MiMoProvider(model="opencode/MiMo-V2.5-Pro", api_key="tp-test", base_url="https://token-plan-sgp.xiaomimimo.com/v1", offline=False)

    assert provider.model == "mimo-v2.5-pro"


def test_mimo_canonicalizes_legacy_lowercase_setting():
    provider = MiMoProvider(model="mimo-v2.5-pro", api_key="tp-test", base_url="https://token-plan-sgp.xiaomimimo.com/v1", offline=False)

    assert provider.model == "mimo-v2.5-pro"


def test_mimo_resolves_api_key_from_explicit_env_only(monkeypatch):
    monkeypatch.delenv("XIAOMI_MIMO_API_KEY", raising=False)
    monkeypatch.delenv("MIMO_API_KEY", raising=False)
    assert mimo._resolve_api_key() is None

    monkeypatch.setenv("MIMO_API_KEY", "tp-env")
    assert mimo._resolve_api_key() == "tp-env"

    monkeypatch.setenv("XIAOMI_MIMO_API_KEY", "tp-xiaomi")
    assert mimo._resolve_api_key() == "tp-xiaomi"


def test_mimo_resolves_base_url_aliases(monkeypatch):
    monkeypatch.delenv("XIAOMI_MIMO_BASE_URL", raising=False)
    monkeypatch.delenv("MIMO_BASE_URL", raising=False)
    assert mimo._resolve_base_url() == "https://api.xiaomimimo.com/v1"

    monkeypatch.setenv("MIMO_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1/")
    assert mimo._resolve_base_url() == "https://token-plan-sgp.xiaomimimo.com/v1"

    monkeypatch.setenv("XIAOMI_MIMO_BASE_URL", "https://token-plan-ams.xiaomimimo.com/v1/")
    assert mimo._resolve_base_url() == "https://token-plan-ams.xiaomimimo.com/v1"


def test_mimo_defaults_to_offline_without_explicit_key(monkeypatch):
    monkeypatch.delenv("XIAOMI_MIMO_API_KEY", raising=False)
    monkeypatch.delenv("MIMO_API_KEY", raising=False)

    provider = MiMoProvider(model="mimo-v2.5-pro")

    assert provider.offline is True
    assert provider.call("research", "hello").provider == "mimo"
