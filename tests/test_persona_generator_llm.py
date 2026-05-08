from __future__ import annotations

import json

import pytest

from src.council.persona_generator import PersonaGenerator
from src.execution.models import ModelResult
from src.runtime.live_mode import LiveModeViolation


class MockGateway:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, str]] = []

    def call(self, stage: str, prompt: str, **kwargs) -> ModelResult:
        self.calls.append({"stage": stage, "prompt": prompt, "kwargs": dict(kwargs)})
        if not self.responses:
            raise RuntimeError("no mock response left")
        return ModelResult(text=self.responses.pop(0), provider="mock")


class LiveViolationGateway:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def call(self, stage: str, prompt: str, **kwargs) -> ModelResult:
        self.calls.append({"stage": stage, "prompt": prompt})
        raise LiveModeViolation("live mode rejected mock persona output")


class TimeoutGateway:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def call(self, stage: str, prompt: str, **kwargs) -> ModelResult:
        self.calls.append({"stage": stage, "prompt": prompt, "kwargs": dict(kwargs)})
        raise TimeoutError("council provider call timed out after 20s")


class ProviderAuthFailureGateway:
    def __init__(self, message: str) -> None:
        self.message = message
        self.calls: list[dict[str, str]] = []

    def call(self, stage: str, prompt: str, **kwargs) -> ModelResult:
        self.calls.append({"stage": stage, "prompt": prompt, "kwargs": dict(kwargs)})
        raise RuntimeError(self.message)


def _ontology():
    return {
        "topic": "orchard disease detection kit market",
        "roles": ["evidence_reviewer", "market_analyst"],
        "intents": [
            "Summarize grounded evidence and report uncertainty.",
            "Compare public market signals with cited sources.",
        ],
        "allowed_tools": ["read_file", "search_index"],
        "required_outputs": ["report", "citations"],
        "value_axes": {
            "time_horizon": "long",
            "risk_tolerance": 0.2,
            "stakeholder_priority": ["primary", "secondary", "tertiary"],
            "innovation_orientation": 0.7,
        },
    }


def _proposal_response() -> str:
    return json.dumps(
        {
            "personas": [
                {
                    "persona_id": "persona-llm-001",
                    "name": "Evidence Judge",
                    "role": "evidence_reviewer",
                    "intent": "Judge orchard disease detection claims against cited evidence.",
                    "allowed_tools": ["read_file"],
                    "required_outputs": ["report", "citations"],
                    "value_axes": {
                        "time_horizon": "long",
                        "risk_tolerance": 0.1,
                        "stakeholder_priority": ["primary", "secondary"],
                        "innovation_orientation": 0.4,
                    },
                    "manifest": {"topic_fit": "evidence quality"},
                },
                {
                    "persona_id": "persona-llm-002",
                    "name": "Market Mapper",
                    "role": "market_analyst",
                    "intent": "Map buyer demand and competing disease detection alternatives.",
                    "allowed_tools": ["search_index"],
                    "required_outputs": ["report", "citations"],
                    "value_axes": {
                        "time_horizon": "mid",
                        "risk_tolerance": 0.3,
                        "stakeholder_priority": ["primary", "secondary", "tertiary"],
                        "innovation_orientation": 0.8,
                    },
                    "topic_fit": "market demand",
                },
            ]
        }
    )


def test_propose_with_llm_converts_json_to_drafts():
    gateway = MockGateway([_proposal_response()])
    generator = PersonaGenerator(gateway=gateway)

    drafts = generator.propose_with_llm(_ontology(), target_count=2, topic="orchard disease")

    assert [draft.persona_id for draft in drafts] == ["persona-llm-001", "persona-llm-002"]
    assert drafts[0].name == "Evidence Judge"
    assert drafts[0].role == "evidence_reviewer"
    assert drafts[0].allowed_tools == ["read_file"]
    assert drafts[0].manifest["topic_fit"] == "evidence quality"
    assert drafts[1].manifest["topic_fit"] == "market demand"
    assert gateway.calls[0]["stage"] == "council"
    assert gateway.calls[0]["kwargs"]["council_stage"] == "persona_propose"
    assert gateway.calls[0]["kwargs"]["layer_id"] == "persona_generation"
    assert gateway.calls[0]["kwargs"]["max_tokens"] == 4096
    assert "HACHIMI Stage 1 PROPOSE" in gateway.calls[0]["prompt"]


def test_propose_with_llm_falls_back_to_heuristic_on_broken_response():
    gateway = MockGateway(["not json"])
    generator = PersonaGenerator(gateway=gateway)

    drafts = generator.propose_with_llm(_ontology(), target_count=2, topic="orchard disease")

    assert [draft.persona_id for draft in drafts] == ["persona-001", "persona-002"]
    assert drafts[0].name == "Evidence Reviewer 1"
    assert gateway.calls[0]["stage"] == "council"


def test_propose_with_llm_propagates_mock_live_mode_violation():
    gateway = LiveViolationGateway()
    generator = PersonaGenerator(gateway=gateway)

    try:
        generator.propose_with_llm(_ontology(), target_count=2, topic="orchard disease")
        raised = False
    except LiveModeViolation:
        raised = True

    assert raised is True
    assert gateway.calls[0]["stage"] == "council"


def test_propose_with_llm_propagates_empty_live_output_violation():
    class EmptyLiveOutputGateway:
        def __init__(self) -> None:
            self.calls = []

        def call(self, stage: str, prompt: str, **kwargs) -> ModelResult:
            self.calls.append({"stage": stage, "prompt": prompt, "kwargs": dict(kwargs)})
            raise LiveModeViolation("live mode rejected empty or too-short model output at stage 'council'")

    gateway = EmptyLiveOutputGateway()
    generator = PersonaGenerator(gateway=gateway)

    with pytest.raises(LiveModeViolation, match="empty or too-short"):
        generator.propose_with_llm(_ontology(), target_count=2, topic="orchard disease")

    assert gateway.calls[0]["kwargs"]["council_stage"] == "persona_propose"


def test_propose_with_llm_propagates_provider_timeout():
    gateway = TimeoutGateway()
    generator = PersonaGenerator(gateway=gateway)

    with pytest.raises(TimeoutError, match="council provider call timed out"):
        generator.propose_with_llm(_ontology(), target_count=2, topic="orchard disease")

    assert gateway.calls[0]["kwargs"]["council_stage"] == "persona_propose"


@pytest.mark.parametrize(
    "message",
    [
        "MiMo API HTTP 401: invalid_key",
        "HTTP Error 403: Forbidden",
        "OpenCode API key is not configured",
        "Cloudflare 1010 access denied",
    ],
)
def test_propose_with_llm_reraises_provider_auth_or_policy_failures(message: str):
    gateway = ProviderAuthFailureGateway(message)
    generator = PersonaGenerator(gateway=gateway)

    with pytest.raises(RuntimeError, match=message.split()[0]):
        generator.propose_with_llm(_ontology(), target_count=2, topic="orchard disease")

    assert gateway.calls[0]["kwargs"]["council_stage"] == "persona_propose"


def test_deep_validate_llm_adds_issue_for_low_relevance():
    gateway = MockGateway([json.dumps({"score": 2, "reason": "not topic relevant"})])
    generator = PersonaGenerator(gateway=gateway)
    draft = generator.propose(_ontology(), target_count=1)[0]

    report = generator.deep_validate([draft], _ontology(), topic_keywords=["orchard", "disease"])

    assert report.valid_ids == []
    assert any(issue.code == "deep.llm_topic_relevance" for issue in report.issues)
    assert gateway.calls[0]["kwargs"]["council_stage"] == "persona_deep_validate"
    assert gateway.calls[0]["kwargs"]["layer_id"] == "persona_generation"
    assert gateway.calls[0]["kwargs"]["max_tokens"] == 4096
    assert "HACHIMI Stage 2 DEEP VALIDATE" in gateway.calls[0]["prompt"]


def test_deep_validate_llm_can_be_disabled_for_bounded_live_verification(monkeypatch):
    monkeypatch.setenv("MUCHANIPO_PERSONA_LLM_DEEP_VALIDATE", "0")
    gateway = TimeoutGateway()
    generator = PersonaGenerator(gateway=gateway)
    draft = generator.propose(_ontology(), target_count=1)[0]

    report = generator.deep_validate([draft], _ontology())

    assert report.valid_ids == [draft.persona_id]
    assert report.issues == []
    assert gateway.calls == []



def test_deep_validate_llm_propagates_live_mode_violation():
    gateway = LiveViolationGateway()
    generator = PersonaGenerator(gateway=gateway)
    draft = generator.propose(_ontology(), target_count=1)[0]

    try:
        generator.deep_validate([draft], _ontology(), topic_keywords=["orchard", "disease"])
        raised = False
    except LiveModeViolation:
        raised = True

    assert raised is True
    assert gateway.calls[0]["stage"] == "council"


def test_deep_validate_llm_propagates_empty_live_output_violation():
    class EmptyLiveOutputGateway:
        def __init__(self) -> None:
            self.calls = []

        def call(self, stage: str, prompt: str, **kwargs) -> ModelResult:
            self.calls.append({"stage": stage, "prompt": prompt, "kwargs": dict(kwargs)})
            raise LiveModeViolation("live mode rejected empty or too-short model output at stage 'council'")

    gateway = EmptyLiveOutputGateway()
    generator = PersonaGenerator(gateway=gateway)
    draft = generator.propose(_ontology(), target_count=1)[0]

    with pytest.raises(LiveModeViolation, match="empty or too-short"):
        generator.deep_validate([draft], _ontology(), topic_keywords=["orchard", "disease"])

    assert generator._deep_validate_failures == 0
    assert gateway.calls[0]["kwargs"]["council_stage"] == "persona_deep_validate"


def test_persona_council_max_tokens_are_env_tunable(monkeypatch):
    monkeypatch.setenv("MUCHANIPO_PERSONA_COUNCIL_MAX_TOKENS", "6144")
    gateway = MockGateway([_proposal_response()])
    generator = PersonaGenerator(gateway=gateway)

    generator.propose_with_llm(_ontology(), target_count=1, topic="orchard disease")

    assert gateway.calls[0]["kwargs"]["max_tokens"] == 6144


@pytest.mark.parametrize(
    "message",
    [
        "MiMo API HTTP 401: invalid_key",
        "HTTP Error 403: Forbidden",
        "OpenCode API key is not configured",
        "Cloudflare 1010 access denied",
    ],
)
def test_deep_validate_llm_reraises_provider_auth_or_policy_failures(message: str):
    gateway = ProviderAuthFailureGateway(message)
    generator = PersonaGenerator(gateway=gateway)
    draft = generator.propose(_ontology(), target_count=1)[0]

    with pytest.raises(RuntimeError, match=message.split()[0]):
        generator.deep_validate([draft], _ontology(), topic_keywords=["orchard", "disease"])

    assert gateway.calls[0]["kwargs"]["council_stage"] == "persona_deep_validate"


def test_deep_validate_llm_catches_provider_timeout_and_skips():
    gateway = TimeoutGateway()
    generator = PersonaGenerator(gateway=gateway)
    draft = generator.propose(_ontology(), target_count=1)[0]

    report = generator.deep_validate([draft], _ontology(), topic_keywords=["orchard", "disease"])
    # Timeout is caught, failure counter increments, validation completes without raising.
    assert generator._deep_validate_failures == 1
    assert gateway.calls[0]["kwargs"]["council_stage"] == "persona_deep_validate"


def test_generate_uses_llm_mode_when_gateway_is_present():
    gateway = MockGateway(
        [
            _proposal_response(),
            json.dumps({"score": 9, "reason": "relevant"}),
            json.dumps({"score": 8, "reason": "relevant"}),
        ]
    )
    generator = PersonaGenerator(gateway=gateway)

    finals, telemetry = generator.generate(
        _ontology(),
        target_count=2,
        topic="orchard disease detection kit market",
    )

    assert [final.name for final in finals] == ["Evidence Judge", "Market Mapper"]
    assert telemetry["fallbacks_used"] == 0
    assert len(gateway.calls) == 3
    assert "HACHIMI Stage 1 PROPOSE" in gateway.calls[0]["prompt"]


def test_generate_propagates_caller_topic_to_llm_deep_validate_when_ontology_lacks_topic():
    gateway = MockGateway(
        [
            _proposal_response(),
            json.dumps({"score": 9, "reason": "relevant"}),
            json.dumps({"score": 8, "reason": "relevant"}),
        ]
    )
    generator = PersonaGenerator(gateway=gateway)
    ontology = dict(_ontology())
    ontology.pop("topic")
    caller_topic = "caller supplied orchard disease buyer research"

    finals, _telemetry = generator.generate(
        ontology,
        target_count=2,
        topic=caller_topic,
    )

    assert [final.name for final in finals] == ["Evidence Judge", "Market Mapper"]
    assert caller_topic in gateway.calls[0]["prompt"]
    assert caller_topic in gateway.calls[1]["prompt"]
    assert caller_topic in gateway.calls[2]["prompt"]


def test_generate_without_gateway_keeps_heuristic_mode():
    generator = PersonaGenerator()

    finals, telemetry = generator.generate(_ontology(), target_count=2)

    assert [final.persona_id for final in finals] == ["persona-001", "persona-002"]
    assert finals[0].name == "Evidence Reviewer 1"
    assert telemetry["fallbacks_used"] == 0


def test_generate_can_disable_fallback_fill_for_live_mode():
    generator = PersonaGenerator()

    finals, telemetry = generator.generate(
        _ontology(),
        target_count=2,
        topic_keywords=["quantum", "computing"],
        allow_fallbacks=False,
    )

    assert finals == []
    assert telemetry["fallbacks_used"] == 0
    assert telemetry["deep_failed_ids"] == ["persona-001", "persona-002"]
