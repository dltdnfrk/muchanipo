"""Model Gateway v2 routing + fallback chain tests (PRD-v2 §8.1)."""

from __future__ import annotations

import pytest

from src.execution.gateway_v2 import (
    FALLBACK_CHAIN,
    PRIMARY_ROUTES,
    FallbackChain,
    GatewayV2,
    build_default_providers,
    default_gateway,
)
from src.execution.models import ModelResult
from src.execution.providers.anthropic import AnthropicProvider


# ---- offline mock providers ----------------------------------------------


def test_default_offline_providers_return_mock_text():
    providers = build_default_providers(force_offline=True)
    for name in ("anthropic", "gemini", "kimi", "codex"):
        result = providers[name].call(stage="research", prompt="hello")
        assert "[mock-" in result.text
        assert result.provider == name


def test_anthropic_provider_present_in_default_set():
    providers = build_default_providers(force_offline=True)
    assert "anthropic" in providers
    assert "opencode" in providers
    assert "mock" in providers


def test_default_providers_prefer_local_cli_when_requested():
    providers = build_default_providers(force_offline=False, prefer_cli=True)

    assert providers["anthropic"].use_cli is bool(providers["anthropic"].claude_bin)
    assert providers["gemini"].use_cli is bool(providers["gemini"].gemini_bin)
    assert providers["kimi"].use_cli is bool(providers["kimi"].kimi_bin)
    assert providers["codex"].use_cli is bool(providers["codex"].codex_bin)
    assert providers["opencode"].use_cli is bool(providers["opencode"].opencode_bin)


# ---- stage routing -------------------------------------------------------


@pytest.mark.parametrize(
    "stage,expected_primary",
    [
        ("intake", "gemini"),
        ("interview", "anthropic"),
        ("targeting", "gemini"),
        ("research", "gemini"),
        ("evidence", "kimi"),
        ("council", "anthropic"),
        ("report", "anthropic"),
        ("eval", "codex"),
        ("utilities", "opencode"),
        ("implementation_review", "opencode"),
    ],
)
def test_stage_routes_to_correct_primary_provider(stage, expected_primary):
    assert PRIMARY_ROUTES[stage] == expected_primary


def test_default_gateway_routes_council_to_anthropic_class():
    gw = default_gateway(force_offline=True)
    # offline mock anthropic은 raise (mock 키 없음 등) — 그러나 FallbackChain에 의해 다음 시도
    # 그래서 단순 라우팅 값만 확인
    assert gw.stage_routes["council"] == "anthropic"


# ---- FallbackChain primitive --------------------------------------------


class _FailProvider:
    def __init__(self, name: str):
        self.name = name

    def call(self, stage: str, prompt: str, **kwargs):
        raise RuntimeError(f"{self.name} failed")


class _SuccessProvider:
    def __init__(self, name: str):
        self.name = name

    def call(self, stage: str, prompt: str, **kwargs):
        return ModelResult(text=f"ok-{self.name}", provider=self.name, model="mock")


class _AuditRecorder:
    def __init__(self):
        self.calls: list[dict] = []

    def record_call(self, **kwargs):
        self.calls.append(dict(kwargs))


def test_fallback_chain_returns_first_success():
    chain = FallbackChain(name="test", providers=[_SuccessProvider("a"), _FailProvider("b")])
    result = chain.call(stage="test", prompt="x")
    assert result.text == "ok-a"
    assert result.is_fallback is False


def test_fallback_chain_uses_secondary_when_primary_fails():
    chain = FallbackChain(name="test", providers=[_FailProvider("a"), _SuccessProvider("b")])
    result = chain.call(stage="test", prompt="x")
    assert result.text == "ok-b"
    assert result.is_fallback is True
    assert "a failed" in (result.fallback_reason or "")


def test_fallback_chain_exhausts_when_all_fail():
    chain = FallbackChain(
        name="test",
        providers=[_FailProvider("a"), _FailProvider("b"), _FailProvider("c")],
    )
    with pytest.raises(RuntimeError, match="exhausted"):
        chain.call(stage="test", prompt="x")


def test_fallback_chain_callback_invoked_on_each_failure():
    events = []
    chain = FallbackChain(
        name="test",
        providers=[_FailProvider("a"), _FailProvider("b"), _SuccessProvider("c")],
        on_fallback=lambda stage, prov, err: events.append((stage, prov.name)),
    )
    chain.call(stage="X", prompt="x")
    assert events == [("X", "a"), ("X", "b")]


# ---- GatewayV2 ----------------------------------------------------------


def test_gateway_v2_falls_through_chain_to_mock():
    """anthropic / gemini / kimi / codex 모두 안 되면 mock가 잡아야 함."""
    providers = build_default_providers(force_offline=True)
    # offline anthropic은 실제 키 없으면 anthropic.Anthropic 호출 시 raise
    # → fallback chain이 다음 시도

    gw = GatewayV2(
        providers=providers,
        stage_routes=PRIMARY_ROUTES,
        fallback_chain=FALLBACK_CHAIN,
    )
    # interview stage: anthropic → gemini → mock
    result = gw.call("interview", "ping")
    # mock provider가 응답하거나 gemini offline mock이 응답
    assert result.text  # not empty
    assert result.provider in {"anthropic", "gemini", "mock"}


def test_gateway_v2_records_fallback_events_when_primary_fails():
    primary_fails = _FailProvider("primary")
    secondary = _SuccessProvider("secondary")
    gw = GatewayV2(
        providers={"primary": primary_fails, "secondary": secondary},
        stage_routes={"x": "primary"},
        fallback_chain={"x": ["primary", "secondary"]},
    )
    result = gw.call("x", "prompt")
    assert result.text == "ok-secondary"
    assert len(gw.fallback_events) == 1
    assert gw.fallback_events[0]["provider"] == "primary"


def test_gateway_v2_disables_anthropic_provider_fallback_in_chain():
    client = pytest.importorskip("unittest.mock").MagicMock()
    client.messages.create.side_effect = RuntimeError("anthropic down")
    anthropic = AnthropicProvider(api_key="sk-test", client=client, offline=False)
    secondary = _SuccessProvider("gemini")
    gw = GatewayV2(
        providers={"anthropic": anthropic, "gemini": secondary},
        stage_routes={"x": "anthropic"},
        fallback_chain={"x": ["anthropic", "gemini"]},
    )

    result = gw.call("x", "prompt")

    assert result.provider == "gemini"
    assert result.text == "ok-gemini"
    assert gw.fallback_events[0]["provider"] == "anthropic"


def test_gateway_v2_audit_records_actual_fallback_provider():
    audit = _AuditRecorder()
    gw = GatewayV2(
        providers={"primary": _FailProvider("primary"), "secondary": _SuccessProvider("secondary")},
        stage_routes={"x": "primary"},
        fallback_chain={"x": ["primary", "secondary"]},
        audit=audit,
    )

    result = gw.call("x", "prompt")

    assert result.provider == "secondary"
    assert audit.calls[0]["provider"] == "secondary"
    assert "primary failed" in (audit.calls[0]["fallback_reason"] or "")


def test_gateway_v2_unknown_stage_falls_back_to_default_routing():
    """체인 미정의 stage는 기존 ModelGateway 동작으로 폴백."""
    primary = _SuccessProvider("default")
    gw = GatewayV2(
        providers={"default": primary},
        stage_routes={"unknown": "default"},
        fallback_chain={},  # empty
    )
    result = gw.call("unknown", "prompt")
    assert result.text == "ok-default"


def test_gateway_v2_empty_chain_raises_keyerror():
    primary = _SuccessProvider("a")
    gw = GatewayV2(
        providers={"a": primary},
        stage_routes={"x": "a"},
        fallback_chain={"x": ["nonexistent"]},
    )
    with pytest.raises(KeyError, match="no resolvable providers"):
        gw.call("x", "prompt")


# ---- budget integration --------------------------------------------------


class _BudgetTracker:
    def __init__(self, max_usd: float = 1.0):
        self.max = max_usd
        self.calls: list[dict] = []
        self.next_id = 0

    def estimate(self, stage, prompt, provider):
        return 0.01

    def reserve(self, stage, estimated_usd, **metadata):
        self.next_id += 1
        self.calls.append({
            "action": "reserve",
            "stage": stage,
            "usd": estimated_usd,
            "id": self.next_id,
            **metadata,
        })
        return self.next_id

    def reconcile(self, reservation_id, actual_usd):
        self.calls.append({"action": "reconcile", "id": reservation_id, "usd": actual_usd})


def test_gateway_v2_calls_budget_reserve_and_reconcile():
    tracker = _BudgetTracker()
    gw = GatewayV2(
        providers={"a": _SuccessProvider("a")},
        stage_routes={"x": "a"},
        fallback_chain={"x": ["a"]},
        budget=tracker,
    )
    gw.call("x", "prompt")
    actions = [c["action"] for c in tracker.calls]
    assert actions == ["reserve", "reconcile"]


def test_gateway_v2_reserve_records_provider_and_model_metadata():
    tracker = _BudgetTracker()
    gw = GatewayV2(
        providers={"codex": _SuccessProvider("codex")},
        stage_routes={"eval": "codex"},
        fallback_chain={"eval": ["codex"]},
        budget=tracker,
    )

    gw.call("eval", "prompt")

    reserve = next(c for c in tracker.calls if c["action"] == "reserve")
    assert reserve["provider"] == "codex"
    assert reserve["model"] == "gpt-5.4"


def test_gateway_v2_budget_audit_records_actual_fallback_provider():
    audit = _AuditRecorder()
    tracker = _BudgetTracker()
    gw = GatewayV2(
        providers={"primary": _FailProvider("primary"), "secondary": _SuccessProvider("secondary")},
        stage_routes={"x": "primary"},
        fallback_chain={"x": ["primary", "secondary"]},
        budget=tracker,
        audit=audit,
    )

    result = gw.call("x", "prompt")

    assert result.provider == "secondary"
    assert audit.calls[0]["provider"] == "secondary"


def test_gateway_v2_reconciles_zero_when_chain_exhausted():
    tracker = _BudgetTracker()
    gw = GatewayV2(
        providers={"a": _FailProvider("a")},
        stage_routes={"x": "a"},
        fallback_chain={"x": ["a"]},
        budget=tracker,
    )
    with pytest.raises(RuntimeError):
        gw.call("x", "prompt")
    reconcile = next(c for c in tracker.calls if c["action"] == "reconcile")
    assert reconcile["usd"] == 0.0
