from __future__ import annotations

import json
import time

import pytest

from src.council.parsers import parse_council_response
from src.council.persona_generator import FinalPersona
from src.council.prompts import build_round_prompt
from src.council.oasis_camel_runtime import validate_protocol_trace
from src.council.round_layers import DEFAULT_LAYERS
from src.council.session import PlateauDetector, Session
from src.execution.gateway_v2 import GatewayV2
from src.execution.models import ModelResult
from src.runtime.live_mode import LiveModeViolation


class SequenceProvider:
    name = "sequence"

    def __init__(self, confidences: list[float]) -> None:
        self.confidences = list(confidences)
        self.calls: list[dict[str, object]] = []

    def call(self, stage: str, prompt: str, **kwargs) -> ModelResult:
        self.calls.append({"stage": stage, "prompt": prompt, "kwargs": dict(kwargs)})
        idx = len(self.calls)
        confidence = self.confidences[idx - 1]
        payload = {
            "key_claim": f"round {idx} chairman synthesis",
            "body_claims": [f"supporting claim {idx}", "shared evidence-backed claim"],
            "evidence_ref_ids": [f"E{idx}"],
            "confidence_score": confidence,
            "disagreements": ["one unresolved assumption"],
            "next_actions": ["verify cited evidence"],
            "framework_output": {"framework": "MECE Tree"},
        }
        return ModelResult(text=json.dumps(payload), provider=self.name)


class SlowProvider:
    name = "slow"

    def call(self, stage: str, prompt: str, **kwargs) -> ModelResult:
        time.sleep(0.2)
        return ModelResult(text='{"key_claim":"late"}', provider=self.name)


class SlowChairmanProvider:
    name = "slow_chairman"

    def call(self, stage: str, prompt: str, **kwargs) -> ModelResult:
        council_stage = kwargs.get("council_stage")
        if council_stage == "chairman":
            time.sleep(0.2)
            return ModelResult(text='{"key_claim":"late chairman"}', provider=self.name)
        payload = {
            "key_claim": f"{council_stage} claim",
            "body_claims": ["source-backed claim"],
            "evidence_ref_ids": ["E1"],
            "confidence_score": 0.7,
            "disagreements": ["needs validation"],
            "next_actions": ["verify source"],
        }
        return ModelResult(text=json.dumps(payload), provider=self.name)


class EmptyThenCompactProvider:
    name = "empty_then_compact"

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def call(self, stage: str, prompt: str, **kwargs) -> ModelResult:
        self.calls.append({"stage": stage, "prompt": prompt, "council_stage": kwargs.get("council_stage", "")})
        if "Return only valid JSON. No markdown." not in prompt:
            return ModelResult(text="", provider=self.name, model="live-empty-fixture")
        if kwargs.get("council_stage") == "peer_review":
            payload = {
                "stance": "mixed",
                "critiques": ["needs source specificity"],
                "agreements": ["market evidence matters"],
                "suggested_revision": "cite the strongest evidence IDs",
                "confidence_score": 0.66,
            }
        else:
            payload = {
                "key_claim": "compact retry recovered a source-backed council turn",
                "body_claims": ["market coverage is adequate after source routing"],
                "evidence_ref_ids": ["E1"],
                "confidence_score": 0.72,
                "disagreements": ["price sensitivity remains uncertain"],
                "next_actions": ["verify farmer willingness-to-pay"],
            }
        return ModelResult(text=json.dumps(payload), provider=self.name, model="live-compact-fixture")


class OpenCodeEmptyThenMimoProvider:
    name = "opencode"
    model = "opencode/kimi-k2.6"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def call(self, stage: str, prompt: str, **kwargs) -> ModelResult:
        self.calls.append({"stage": stage, "prompt": prompt, "kwargs": dict(kwargs)})
        retry_model = kwargs.get("model")
        if retry_model != "opencode/mimo-v2.5-pro":
            raise LiveModeViolation("live mode rejected empty or too-short model output at stage 'council'")
        if kwargs.get("council_stage") == "peer_review":
            payload = {
                "stance": "mixed",
                "critiques": ["retry should keep evidence IDs explicit"],
                "agreements": ["allowed OpenCode Go fallback is still live"],
                "suggested_revision": "keep compact prompt telemetry",
                "confidence_score": 0.67,
            }
        else:
            payload = {
                "key_claim": "mimo OpenCode retry recovered empty council output",
                "body_claims": ["the retry stayed inside the allowed OpenCode Go model family"],
                "evidence_ref_ids": ["E1"],
                "confidence_score": 0.73,
                "disagreements": ["retry telemetry must remain visible"],
                "next_actions": ["keep live auth and mock failures blocking"],
            }
        return ModelResult(text=json.dumps(payload), provider=self.name, model=str(retry_model))


class AuthFailureProvider:
    name = "opencode"
    model = "opencode/mimo-v2.5-pro"

    def __init__(self, message: str) -> None:
        self.message = message
        self.calls: list[dict[str, object]] = []

    def call(self, stage: str, prompt: str, **kwargs) -> ModelResult:
        self.calls.append({"stage": stage, "prompt": prompt, "kwargs": dict(kwargs)})
        raise RuntimeError(self.message)


class MockLiveProvider:
    name = "opencode"
    model = "opencode/mimo-v2.5-pro"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def call(self, stage: str, prompt: str, **kwargs) -> ModelResult:
        self.calls.append({"stage": stage, "prompt": prompt, "kwargs": dict(kwargs)})
        return ModelResult(
            text="[mock-opencode/council] placeholder council output",
            provider=self.name,
            model=self.model,
        )


def _gateway(provider) -> GatewayV2:
    return GatewayV2(
        providers={provider.name: provider},
        stage_routes={"council": provider.name},
        fallback_chain={"council": [provider.name]},
    )


def _persona() -> FinalPersona:
    return FinalPersona(
        persona_id="p1",
        name="MiroFish",
        role="skeptical reviewer",
        manifest={"intent": "challenge weak claims", "required_outputs": ["risks"]},
    )


def test_session_run_all_calls_gateway_v2_for_ten_structured_rounds():
    provider = SequenceProvider([
        0.10, 0.10, 0.10,
        0.20, 0.20, 0.20,
        0.30, 0.30, 0.30,
        0.45, 0.45, 0.45,
        0.55, 0.55, 0.55,
        0.66, 0.66, 0.66,
        0.74, 0.74, 0.74,
        0.82, 0.82, 0.82,
        0.89, 0.89, 0.89,
        0.95, 0.95, 0.95,
    ])
    session = Session(
        gateway=_gateway(provider),
        layers=list(DEFAULT_LAYERS),
        personas=[_persona()],
        plateau=PlateauDetector(window=3, tolerance=0.05),
    )

    results = session.run_all()

    assert len(results) == 10
    assert len(provider.calls) == 30
    assert all(call["stage"] == "council" for call in provider.calls)
    assert results[0].key_claim == "round 3 chairman synthesis"
    assert results[-1].confidence_score == 0.95
    assert "시장 규모 + 컨텍스트" in provider.calls[0]["prompt"]
    assert DEFAULT_LAYERS[0].focus_question in provider.calls[0]["prompt"]
    assert ", ".join(DEFAULT_LAYERS[0].emphasis_roles) in provider.calls[0]["prompt"]
    assert "Individual Analysis" in provider.calls[0]["prompt"]
    assert "Anonymous Peer Review" in provider.calls[1]["prompt"]
    assert "Chairman Synthesis" in provider.calls[2]["prompt"]


def test_session_emits_council_progress_while_round_runs():
    provider = SequenceProvider([0.70, 0.72, 0.74])
    events: list[dict[str, object]] = []
    session = Session(
        gateway=_gateway(provider),
        layers=list(DEFAULT_LAYERS[:1]),
        personas=[_persona()],
        plateau=PlateauDetector(window=3, tolerance=0.05),
        progress_callback=events.append,
    )

    session.run_one_round(1)

    assert events[0]["event"] == "council_round_start"
    assert events[0]["round"] == 1
    assert events[0]["protocol_runtime"] == "clean-room local social simulation protocol"
    assert events[0]["protocol_phase_count"] == 3
    assert validate_protocol_trace(events[0]["protocol_trace"])
    assert validate_protocol_trace(session.protocol_traces_by_round[1])
    assert events[0]["protocol_trace"]["world_state"]["peer_review_graph"] == "round_robin_blinded"
    assert events[0]["protocol_trace"]["agent_states"][0]["memory"]
    assert events[0]["protocol_trace"]["interaction_events"]
    turns = [event for event in events if event["event"] == "council_turn"]
    tokens = [event for event in events if event["event"] == "council_persona_token"]
    assert [event["stage"] for event in turns] == [
        "council_progress",
        "council_progress",
        "council_progress",
    ]
    assert [event["pipeline_stage"] for event in turns] == ["council", "council", "council"]
    assert [event["council_stage"] for event in turns] == ["individual", "peer_review", "chairman"]
    assert len(tokens) == 3
    assert all(str(event["delta"]).strip() for event in tokens)
    assert {event["visualization_source"] for event in tokens} == {"raw"}
    assert events[-1]["event"] == "council_round_done"
    assert events[-1]["round"] == 1


def test_session_emits_provider_call_progress_events():
    provider = SequenceProvider([0.70, 0.72, 0.74])
    events: list[dict[str, object]] = []
    session = Session(
        gateway=_gateway(provider),
        layers=list(DEFAULT_LAYERS[:1]),
        personas=[_persona()],
        plateau=PlateauDetector(window=3, tolerance=0.05),
        progress_callback=events.append,
    )

    session.run_one_round(1)

    starts = [event for event in events if event["event"] == "council_provider_call_start"]
    dones = [event for event in events if event["event"] == "council_provider_call_done"]
    assert [event["council_stage"] for event in starts] == [
        "individual",
        "peer_review",
        "chairman",
    ]
    assert [event["council_stage"] for event in dones] == [
        "individual",
        "peer_review",
        "chairman",
    ]
    assert starts[0]["provider_route"] == "sequence"
    assert starts[0]["round"] == 1
    assert starts[0]["layer"] == DEFAULT_LAYERS[0].layer_id
    assert starts[0]["prompt_chars"] > 0
    assert dones[-1]["response_chars"] > 0
    assert provider.calls[0]["kwargs"]["max_tokens"] == 4096


def test_session_council_max_tokens_are_env_tunable(monkeypatch):
    monkeypatch.setenv("MUCHANIPO_COUNCIL_PEER_REVIEW_MAX_TOKENS", "6144")
    provider = SequenceProvider([0.70, 0.72, 0.74])
    session = Session(
        gateway=_gateway(provider),
        layers=list(DEFAULT_LAYERS[:1]),
        personas=[_persona()],
        plateau=PlateauDetector(window=3, tolerance=0.05),
    )

    session.run_one_round(1)

    assert provider.calls[0]["kwargs"]["max_tokens"] == 4096
    assert provider.calls[1]["kwargs"]["max_tokens"] == 6144
    assert provider.calls[2]["kwargs"]["max_tokens"] == 4096


def test_session_watchdog_accepts_provider_timeout_alias(monkeypatch):
    monkeypatch.setenv("MUCHANIPO_COUNCIL_PROVIDER_TIMEOUT_SEC", "0.01")
    events: list[dict[str, object]] = []
    session = Session(
        gateway=_gateway(SlowProvider()),
        layers=list(DEFAULT_LAYERS[:1]),
        personas=[_persona()],
        plateau=PlateauDetector(window=3, tolerance=0.05),
        progress_callback=events.append,
    )

    with pytest.raises(TimeoutError, match="council provider call timed out"):
        session.run_one_round(1)

    event_names = [event["event"] for event in events]
    assert "council_provider_call_start" in event_names
    assert "council_provider_call_timeout" in event_names
    assert "council_turn" not in event_names
    timeout_event = next(event for event in events if event["event"] == "council_provider_call_timeout")
    assert timeout_event["provider_route"] == "slow"
    assert timeout_event["council_stage"] == "individual"
    assert timeout_event["blocks_product_pass"] is True


def test_session_can_synthesize_chairman_after_timeout_when_enabled(monkeypatch):
    monkeypatch.setenv("MUCHANIPO_COUNCIL_PROVIDER_TIMEOUT_SEC", "0.01")
    monkeypatch.setenv("MUCHANIPO_CHAIRMAN_TIMEOUT_FALLBACK", "1")
    events: list[dict[str, object]] = []
    session = Session(
        gateway=_gateway(SlowChairmanProvider()),
        layers=list(DEFAULT_LAYERS[:1]),
        personas=[_persona()],
        plateau=PlateauDetector(window=3, tolerance=0.05),
        progress_callback=events.append,
    )

    result = session.run_one_round(1)

    event_names = [event["event"] for event in events]
    assert "council_provider_call_timeout" in event_names
    assert events[-1]["event"] == "council_round_done"
    chairman_turn = [event for event in events if event["event"] == "council_turn"][-1]
    assert chairman_turn["council_stage"] == "chairman"
    assert chairman_turn["provider"] == "local_timeout_fallback"
    assert "timed out" in result.raw_response


def test_session_compact_retries_empty_live_council_outputs(monkeypatch):
    monkeypatch.setenv("MUCHANIPO_REQUIRE_LIVE", "1")
    provider = EmptyThenCompactProvider()
    events: list[dict[str, object]] = []
    session = Session(
        gateway=_gateway(provider),
        layers=list(DEFAULT_LAYERS[:1]),
        personas=[_persona()],
        plateau=PlateauDetector(window=3, tolerance=0.05),
        progress_callback=events.append,
    )

    result = session.run_one_round(1)

    assert result.key_claim == "compact retry recovered a source-backed council turn"
    assert len(provider.calls) == 6
    retry_starts = [event for event in events if event.get("retry") == "compact_council_prompt" and event["event"] == "council_provider_call_start"]
    assert [event["council_stage"] for event in retry_starts] == ["individual", "peer_review", "chairman"]
    assert events[-1]["event"] == "council_round_done"
    turns = [event for event in events if event["event"] == "council_turn"]
    assert len(turns) == 3


def test_session_empty_retry_uses_allowed_opencode_go_model(monkeypatch):
    monkeypatch.setenv("MUCHANIPO_REQUIRE_LIVE", "1")
    monkeypatch.setenv("MUCHANIPO_COUNCIL_EMPTY_RETRY_MODELS", "opencode/mimo-v2.5-pro")
    provider = OpenCodeEmptyThenMimoProvider()
    events: list[dict[str, object]] = []
    session = Session(
        gateway=_gateway(provider),
        layers=list(DEFAULT_LAYERS[:1]),
        personas=[_persona()],
        plateau=PlateauDetector(window=3, tolerance=0.05),
        progress_callback=events.append,
    )

    result = session.run_one_round(1)

    assert result.key_claim == "mimo OpenCode retry recovered empty council output"
    retry_calls = [call for call in provider.calls if call["kwargs"].get("model") == "opencode/mimo-v2.5-pro"]
    assert len(retry_calls) == 3
    retry_starts = [
        event
        for event in events
        if event.get("retry") == "compact_council_prompt"
        and event["event"] == "council_provider_call_start"
    ]
    assert {event["retry_model"] for event in retry_starts} == {"opencode/mimo-v2.5-pro"}
    first_error = next(event for event in events if event["event"] == "council_provider_call_error")
    assert first_error["failure_kind"] == "empty_live_output"
    assert first_error["blocks_product_pass"] is True


def test_session_does_not_retry_auth_or_policy_failure(monkeypatch):
    monkeypatch.setenv("MUCHANIPO_REQUIRE_LIVE", "1")
    provider = AuthFailureProvider("HTTP Error 403: Forbidden")
    events: list[dict[str, object]] = []
    session = Session(
        gateway=_gateway(provider),
        layers=list(DEFAULT_LAYERS[:1]),
        personas=[_persona()],
        plateau=PlateauDetector(window=3, tolerance=0.05),
        progress_callback=events.append,
    )

    with pytest.raises(RuntimeError, match="403"):
        session.run_one_round(1)

    assert len(provider.calls) == 1
    error_event = next(event for event in events if event["event"] == "council_provider_call_error")
    assert error_event["failure_kind"] == "auth_or_policy_failure"
    assert "retry" not in error_event


def test_session_does_not_retry_mock_live_failure(monkeypatch):
    monkeypatch.setenv("MUCHANIPO_REQUIRE_LIVE", "1")
    provider = MockLiveProvider()
    events: list[dict[str, object]] = []
    session = Session(
        gateway=_gateway(provider),
        layers=list(DEFAULT_LAYERS[:1]),
        personas=[_persona()],
        plateau=PlateauDetector(window=3, tolerance=0.05),
        progress_callback=events.append,
    )

    with pytest.raises(LiveModeViolation, match="placeholder model output"):
        session.run_one_round(1)

    assert len(provider.calls) == 1
    error_event = next(event for event in events if event["event"] == "council_provider_call_error")
    assert error_event["failure_kind"] == "mock_live_output"
    assert "retry" not in error_event


def test_session_can_use_ollama_for_local_council_visualization(monkeypatch):
    provider = SequenceProvider([0.70, 0.72, 0.74])
    events: list[dict[str, object]] = []

    def fake_ollama_call(self, stage, prompt, **kwargs):
        assert stage == "council_visualization"
        assert "Return only the speech bubble text" in prompt
        return ModelResult(text="로컬 요약 발화입니다.", provider="ollama", model=self.model)

    monkeypatch.setenv("MUCHANIPO_COUNCIL_VISUALIZER", "ollama")
    monkeypatch.setenv("MUCHANIPO_COUNCIL_VISUALIZER_MODEL", "qwen-test")
    monkeypatch.setattr("src.execution.providers.ollama.OllamaProvider.call", fake_ollama_call)

    session = Session(
        gateway=_gateway(provider),
        layers=list(DEFAULT_LAYERS[:1]),
        personas=[_persona()],
        plateau=PlateauDetector(window=3, tolerance=0.05),
        progress_callback=events.append,
    )

    session.run_one_round(1)

    tokens = [event for event in events if event["event"] == "council_persona_token"]
    assert len(tokens) == 3
    assert {event["delta"] for event in tokens} == {"로컬 요약 발화입니다."}
    assert {event["visualization_source"] for event in tokens} == {"ollama"}
    assert {event["visualizer_model"] for event in tokens} == {"qwen-test"}


def test_session_run_all_traverses_default_layers_despite_flat_confidence():
    provider = SequenceProvider([0.70] * 30)
    session = Session(
        gateway=_gateway(provider),
        layers=list(DEFAULT_LAYERS),
        personas=[_persona()],
        plateau=PlateauDetector(window=3, tolerance=0.05),
    )

    results = session.run_all()

    assert len(results) == 10
    assert session.stopped is False
    assert "mandatory layers" in (session.stop_reason or "")
    assert len(provider.calls) == 30


def test_round_prompt_includes_layer_framework_guidance():
    persona = _persona()

    assert "MECE Tree" in build_round_prompt(DEFAULT_LAYERS[0], [persona], [])
    assert "Porter 5 Forces" in build_round_prompt(DEFAULT_LAYERS[1], [persona], [])
    assert "JTBD" in build_round_prompt(DEFAULT_LAYERS[2], [persona], [])
    assert "SWOT" in build_round_prompt(DEFAULT_LAYERS[4], [persona], [])
    assert "North Star Tree" in build_round_prompt(DEFAULT_LAYERS[7], [persona], [])


def test_parse_council_response_accepts_markdown_fallback():
    text = """
Key Claim: The market is attractive but evidence quality is mixed.
Confidence: 72%
Framework: Porter 5 Forces

body_claims
- TAM is growing.
- Buyer power remains high.
"""

    result = parse_council_response(text, DEFAULT_LAYERS[1])

    assert result.layer_id == "L2_competitor_landscape"
    assert result.key_claim.startswith("The market is attractive")
    assert result.body_claims == ["TAM is growing.", "Buyer power remains high."]
    assert result.confidence_score == 0.72
    assert result.framework == "Porter 5 Forces"
