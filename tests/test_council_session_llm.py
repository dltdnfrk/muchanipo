from __future__ import annotations

import json

from src.council.parsers import parse_council_response
from src.council.persona_generator import FinalPersona
from src.council.prompts import build_round_prompt
from src.council.round_layers import DEFAULT_LAYERS
from src.council.session import PlateauDetector, Session
from src.execution.gateway_v2 import GatewayV2
from src.execution.models import ModelResult


class SequenceProvider:
    name = "sequence"

    def __init__(self, confidences: list[float]) -> None:
        self.confidences = list(confidences)
        self.calls: list[dict[str, str]] = []

    def call(self, stage: str, prompt: str, **kwargs) -> ModelResult:
        self.calls.append({"stage": stage, "prompt": prompt})
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


def _gateway(provider: SequenceProvider) -> GatewayV2:
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
    assert events[-1]["event"] == "council_round_done"
    assert events[-1]["round"] == 1


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
