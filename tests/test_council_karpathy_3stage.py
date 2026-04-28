from __future__ import annotations

import json

from src.council.karpathy_prompts import build_peer_review_prompt
from src.council.persona_generator import FinalPersona
from src.council.round_layers import DEFAULT_LAYERS
from src.council.session import PlateauDetector, Session
from src.execution.gateway_v2 import GatewayV2
from src.execution.models import ModelResult


class StageProvider:
    name = "stage-provider"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def call(self, stage: str, prompt: str, **kwargs) -> ModelResult:
        self.calls.append({"stage": stage, "prompt": prompt, "kwargs": dict(kwargs)})
        council_stage = kwargs.get("council_stage")
        idx = len(self.calls)
        if council_stage == "individual":
            payload = {
                "key_claim": f"individual claim {idx}",
                "body_claims": [f"individual support {idx}"],
                "evidence_ref_ids": [f"E{idx}"],
                "confidence_score": 0.72,
            }
        elif council_stage == "peer_review":
            payload = {
                "stance": "agree_with_caveat",
                "critiques": [f"peer critique {idx}"],
                "confidence_score": 0.61,
            }
        else:
            payload = {
                "key_claim": "chairman consensus with explicit disagreement",
                "body_claims": ["consensus: proceed", "disagreement: evidence depth remains weak"],
                "evidence_ref_ids": ["E1"],
                "confidence_score": 0.81,
                "disagreements": ["evidence depth remains weak"],
                "next_actions": ["verify cited evidence"],
            }
        return ModelResult(text=json.dumps(payload), provider=self.name)


def _gateway(provider: StageProvider) -> GatewayV2:
    return GatewayV2(
        providers={provider.name: provider},
        stage_routes={"council": provider.name},
        fallback_chain={"council": [provider.name]},
    )


def _persona(persona_id: str, name: str) -> FinalPersona:
    return FinalPersona(
        persona_id=persona_id,
        name=name,
        role="reviewer",
        manifest={"intent": "review", "required_outputs": ["claims"]},
    )


def test_session_run_one_round_uses_three_stage_fanout():
    provider = StageProvider()
    personas = [_persona("p1", "Alpha"), _persona("p2", "Beta")]
    session = Session(
        gateway=_gateway(provider),
        layers=[DEFAULT_LAYERS[0]],
        personas=personas,
        plateau=PlateauDetector(window=3, tolerance=0.05),
    )

    result = session.run_one_round(1)

    assert len(provider.calls) == 6
    assert [call["kwargs"]["council_stage"] for call in provider.calls] == [
        "individual",
        "individual",
        "peer_review",
        "peer_review",
        "chairman",
        "chairman",
    ]
    assert result.key_claim == "chairman consensus with explicit disagreement"
    assert result.disagreements == ["evidence depth remains weak"]


def test_peer_review_prompt_blinds_other_persona_ids():
    persona = _persona("reviewer-1", "Reviewer")
    prompt = build_peer_review_prompt(
        persona,
        [
            {
                "persona_id": "hidden-persona-id",
                "name": "Hidden Name",
                "key_claim": "Market is attractive",
                "body_claims": ["Demand signal exists"],
            }
        ],
        DEFAULT_LAYERS[0],
    )

    assert "Market is attractive" in prompt
    assert "Opinion A" in prompt
    assert "hidden-persona-id" not in prompt
    assert "Hidden Name" not in prompt


def test_plateau_detection_still_applies_after_chairman_results():
    provider = StageProvider()
    session = Session(
        gateway=_gateway(provider),
        layers=list(DEFAULT_LAYERS[:4]),
        personas=[_persona("p1", "Alpha")],
        plateau=PlateauDetector(window=3, tolerance=0.05),
    )

    results = session.run_all()

    assert len(results) == 3
    assert session.stopped is True
    assert "plateau detected" in (session.stop_reason or "")
