"""RED-anchor tests for the expert interviewer Socratic loop primitive.

Defines the behavioral contract for replacing the fixed Q1..Q6 form-fill
sequence in ``src.muchanipo.server._collect_serve_interview_answers`` with a
gap-driven dynamic loop.
"""
from __future__ import annotations

import pytest

from src.interview.expert_interviewer import (
    OntologyGap,
    OntologyState,
    SocraticTurn,
    detect_gaps,
    next_expert_turn,
    update_state_from_answer,
)


def test_initial_state_returns_socratic_turn_targeting_entities_first() -> None:
    state = OntologyState()
    turn = next_expert_turn(
        topic="딸기 농가용 분자진단 키트 시장성",
        prior_turns=[],
        state=state,
    )
    assert turn is not None
    assert turn.target_gap.kind == "entity"
    assert "도메인 객체" in turn.question


def test_question_uses_user_topic_term_not_generic_substitutes() -> None:
    state = OntologyState()
    turn = next_expert_turn(
        topic="딸기 농가용 분자진단 키트",
        prior_turns=[],
        state=state,
    )
    assert turn is not None
    assert "딸기 농가용 분자진단 키트" in turn.question
    lowered = turn.question.lower()
    assert "market" not in lowered
    assert "purpose" not in lowered
    assert "deliverable" not in lowered
    assert "quality bar" not in lowered


def test_questions_avoid_generic_decision_form_anti_pattern() -> None:
    """Across multiple gap types, the question must not reduce to the
    decision-form / PRD-form pattern the user explicitly rejected."""
    state = OntologyState()
    seen_questions: list[str] = []
    for _ in range(6):
        turn = next_expert_turn(topic="topic", prior_turns=[], state=state)
        if turn is None:
            break
        seen_questions.append(turn.question)
        # advance state minimally so the loop targets a new gap next iteration
        state = update_state_from_answer(state, gap=turn.target_gap, answer="placeholder answer")
    assert seen_questions, "loop must produce at least one Socratic turn"
    for question in seen_questions:
        assert "어떤 결정을 내릴" not in question
        assert "어떤 PRD" not in question
        assert "PRD 결정서" not in question


def test_loop_terminates_when_ontology_is_ready() -> None:
    state = OntologyState(
        entities={"딸기": "...", "분자진단키트": "..."},
        actors={"농가": "..."},
        workflows=["현장 채취 → 추출 → 결과 판독"],
        constraints=["가격 5만원 이하"],
    )
    prior = [{"answer": "x"}, {"answer": "y"}]
    turn = next_expert_turn(topic="t", prior_turns=prior, state=state)
    assert turn is None


def test_loop_does_not_terminate_below_min_turns_even_if_state_full() -> None:
    """min_turns floor: avoid single-turn termination from a rich answer."""
    state = OntologyState(
        entities={"a": "...", "b": "..."},
        actors={"x": "..."},
        workflows=["w"],
        constraints=["c"],
    )
    turn = next_expert_turn(topic="t", prior_turns=[], state=state, min_turns=2)
    assert turn is not None


def test_loop_respects_max_turns_hard_cap() -> None:
    state = OntologyState()
    prior = [{"answer": str(i)} for i in range(8)]
    turn = next_expert_turn(topic="t", prior_turns=prior, state=state, max_turns=8)
    assert turn is None


def test_state_update_extracts_entities_from_multiline_answer() -> None:
    state = OntologyState()
    gap = detect_gaps(state)[0]
    assert gap.kind == "entity"
    state = update_state_from_answer(
        state,
        gap=gap,
        answer="딸기 작물\n분자진단 키트\n현장 진단 워크플로우",
    )
    assert len(state.entities) >= 2
    assert state.is_ready_for_research is False  # actors/workflows still missing


def test_state_update_workflow_appends_full_answer() -> None:
    state = OntologyState(entities={"a": "x", "b": "y"}, actors={"농가": "z"})
    gap = next(g for g in detect_gaps(state) if g.kind == "workflow")
    state = update_state_from_answer(state, gap=gap, answer="현장 → 추출 → 판독")
    assert any("판독" in w for w in state.workflows)


def test_state_update_relation_parses_arrow_syntax() -> None:
    state = OntologyState()
    gap = OntologyGap(kind="relation", label="r", why_it_matters="w", confidence=0.7)
    state = update_state_from_answer(state, gap=gap, answer="병원체 → 작물 손실\n진단 → 처치")
    assert len(state.relations) == 2
    assert state.relations[0][0] == "병원체"
    assert state.relations[1][2] == "처치"


def test_excluded_meaning_or_constraint_required_for_ready() -> None:
    """Ontology readiness requires negative space (constraint or excluded meaning)."""
    state = OntologyState(
        entities={"a": "...", "b": "..."},
        actors={"x": "..."},
        workflows=["w"],
    )
    assert state.is_ready_for_research is False


def test_socratic_turn_carries_target_gap_and_rationale() -> None:
    state = OntologyState()
    turn = next_expert_turn(topic="topic", prior_turns=[], state=state)
    assert turn is not None
    assert turn.rationale.strip()
    assert turn.target_gap.confidence > 0
    assert turn.expected_ontology_progress.startswith(turn.target_gap.kind)


def test_coverage_score_grows_monotonically() -> None:
    state = OntologyState()
    s0 = state.coverage_score
    state = update_state_from_answer(
        state,
        gap=OntologyGap(kind="entity", label="x", why_it_matters="y", confidence=0.9),
        answer="딸기\n분자진단 키트",
    )
    s1 = state.coverage_score
    state = update_state_from_answer(
        state,
        gap=OntologyGap(kind="actor", label="x", why_it_matters="y", confidence=0.85),
        answer="농가",
    )
    s2 = state.coverage_score
    assert s0 <= s1 <= s2


def test_socratic_turn_options_use_korean_or_empty() -> None:
    """Optional contrast probes must not reintroduce generic English PRD slots."""
    state = OntologyState()
    turn = next_expert_turn(topic="topic", prior_turns=[], state=state)
    assert turn is not None
    for probe in turn.options:
        label = probe.get("label", "")
        assert "market" not in label.lower()
        assert "purpose" not in label.lower()
        assert "deliverable" not in label.lower()


@pytest.mark.parametrize("topic", [
    "딸기 농가용 분자진단 키트 시장성",
    "한국 65세 이상 1인 가구 재택의료 SaaS",
    "B2B 영업팀 회의록 PRD 자동 생성 도구",
    "AI coding assistant enterprise security gateway",
])
def test_initial_question_is_topic_specific_for_multiple_verticals(topic: str) -> None:
    state = OntologyState()
    turn = next_expert_turn(topic=topic, prior_turns=[], state=state)
    assert turn is not None
    # The user's exact topic line must appear in the question — preserves
    # vertical-neutral routing (no Korean substring dispatch in the policy).
    head = topic.strip().split("\n")[0][:120]
    assert head in turn.question
