"""C32 — real-wire tests for src/interview ↔ src/intent integration.

Validates that the C31 mock skeleton at src/interview/{session,rubric}.py and
src/intake/idea_dump.py now delegates to the entropy-greedy rubric, the
AskUserQuestion option builder, and OfficeHours.reframe() defined in
src/intent/.
"""
from __future__ import annotations

from src.intake.idea_dump import IdeaDump
from src.intent.interview_rubric import InterviewRubric
from src.interview.session import InterviewSession


def test_session_from_idea_attaches_assess_plan_and_rubric():
    idea = IdeaDump(raw_text="AI 알려줘")  # short → deep
    session = InterviewSession.from_idea(idea)
    assert session.plan is not None
    assert session.plan.mode == "deep"
    assert isinstance(session.rubric, InterviewRubric)
    # Default 6-axis Phase 0b v2 rubric
    assert len(session.rubric.items) == 6


def test_next_question_uses_entropy_greedy_order():
    idea = IdeaDump(raw_text="MIRIVA 진단키트 가격 책정 분석")
    session = InterviewSession.from_idea(idea)

    # Initial entropy is uniform → tie-broken by definition order (Q1 first).
    first = session.next_question()
    assert first is not None
    assert first.dimension_id == "Q1_research_question"

    # After answering Q1 with quality 0.8, it should be COVERED and the
    # entropy-greedy walker should advance to Q2 (purpose).
    session.answer("research_question", "MIRIVA 적정 단가는 얼마인가")
    second = session.next_question()
    assert second is not None
    assert second.dimension_id != "Q1_research_question"
    assert second.dimension_id == "Q2_purpose"


def test_question_options_are_topic_specific_and_terminate_with_other():
    idea = IdeaDump(raw_text="한국 농가 사과 화상병 진단키트 가격 분석")
    session = InterviewSession.from_idea(idea)

    options = session.question_options("Q3_context")
    assert isinstance(options, list)
    assert len(options) >= 2
    labels = [o["label"] for o in options]
    assert labels[-1] == "Other"
    # AgTech domain hint should mention 한국
    joined = " ".join(labels)
    assert "한국" in joined


def test_rubric_coverage_gate_drives_quick_complete():
    """Five of six axes covered with quality≥0.7 → entropy rubric clears
    the 0.75 coverage gate; one axis still uncovered (Q4_known) so the
    entropy walker still has work."""
    idea = IdeaDump(raw_text="LangGraph vs CrewAI 비교 분석 — 한국 시장 ROI 정량")
    session = InterviewSession.from_idea(idea)
    session.answer("research_question", "어느 프레임워크가 적합한가")
    session.answer("purpose", "다음 스프린트 의사결정")
    session.answer("context", "한국 SaaS 스타트업")
    session.answer("deliverable_type", "비교 보고서")
    session.answer("quality_bar", "출처 신뢰도 강함")

    rubric = session.rubric
    assert rubric is not None
    # Legacy 5-key dict view → 5/5 == 1.0
    assert session.coverage_score == 1.0
    # Entropy view → 5/6 == 0.833 ≥ 0.75 gate threshold
    assert rubric.coverage_rate() >= 0.75
    assert rubric.is_complete(threshold=0.75) is True
    # …but Q4_known is still uncovered, so the walker still has work.
    pending = rubric.uncovered_dimension_ids()
    assert pending == ["Q4_known"]


def test_idea_dump_to_research_brief_e2e_via_office_hours():
    idea = IdeaDump(raw_text="LangGraph vs CrewAI — 한국 SaaS 의사결정 비교 분석")
    brief = idea.to_research_brief(
        purpose="다음 스프린트 도구 선정",
        deliverable_type="비교 보고서",
        quality_bar="evidence-backed",
        coverage_score=0.8,
    )
    # OfficeHours.reframe() should populate research_question / context /
    # constraints from the design doc, not leave them as the raw idea text.
    assert brief.raw_idea == "LangGraph vs CrewAI — 한국 SaaS 의사결정 비교 분석"
    assert brief.research_question  # populated from pain_root
    assert brief.context  # populated from contrary_framing
    assert isinstance(brief.known_facts, list)
    # The Q3 implicit-capabilities heuristic should fire on '비교'.
    assert any("비교" in cap for cap in brief.known_facts)
    assert brief.is_ready


def test_clarifications_for_quick_mode_returns_short_prompts_when_quick():
    rich = (
        "MIRIVA 진단키트 가격을 한국 농가 시장에서 ROI 정량 분석해줘 "
        "최신 2026 데이터로 출처 신뢰도 높게 비교 검토 부탁"
    )
    session = InterviewSession.from_idea(IdeaDump(raw_text=rich))
    assert session.plan is not None and session.plan.mode == "quick"
    clarifs = session.clarifications_for_quick_mode()
    # Quick mode caps at 2 questions per quick_clarification_questions().
    assert len(clarifs) <= 2
