"""Interview Prompts (Phase 0a~0e) 테스트."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path("src/intent")))
from interview_prompts import (  # type: ignore
    InterviewPlan,
    ModeDecision,
    assess,
    forcing_questions_korean,
    quick_clarification_questions,
    merge_answers_to_text,
    format_designdoc_review,
    format_consensusplan_review,
    route_mode,
    format_mode_routing_decision,
)
from office_hours import OfficeHours  # type: ignore
from plan_review import PlanReview  # type: ignore


# ---------------------------------------------------------------------------
# Phase 0a — assess() triage
# ---------------------------------------------------------------------------
def test_assess_short_input_goes_deep():
    plan = assess("AI 알려줘")
    assert plan.mode == "deep"
    assert len(plan.missing_dimensions) >= 1


def test_assess_empty_input_goes_deep():
    plan = assess("   ")
    assert plan.mode == "deep"


def test_assess_rich_input_goes_quick():
    plan = assess(
        "MIRIVA 진단키트 가격을 한국 농가 시장에서 ROI 정량 분석해줘 "
        "최신 2026 데이터로 출처 신뢰도 높게 비교 검토 부탁"
    )
    assert plan.mode == "quick"
    # timeframe / domain / evaluation / comparison 모두 매칭돼야
    assert len(plan.missing_dimensions) <= 1


def test_assess_missing_dimensions_detection():
    """timeframe + evaluation 빠진 입력 → 둘 다 missing으로."""
    plan = assess("한국 농가 분석")  # domain만 명시, 짧음
    # short → deep mode
    assert plan.mode == "deep"
    assert "timeframe" in plan.missing_dimensions
    assert "evaluation" in plan.missing_dimensions


# ---------------------------------------------------------------------------
# Phase 0b — forcing questions
# ---------------------------------------------------------------------------
def test_forcing_questions_returns_six():
    """PRD-style 리서치 톤의 6 questions — 무엇/왜/맥락/이미 아는 것/산출물 형태/품질."""
    qs = forcing_questions_korean()
    assert len(qs) == 6
    ids = [q["id"] for q in qs]
    assert "Q1_research_question" in ids  # 무엇을
    assert "Q2_purpose" in ids            # 왜
    assert "Q3_context" in ids            # 맥락
    assert "Q4_known" in ids              # 이미 아는 것
    assert "Q5_deliverable" in ids        # 산출물 형태
    assert "Q6_quality" in ids            # 품질 기준


def test_forcing_questions_use_research_tone_not_startup():
    """gstack startup 톤(pain/10-star/scope) 대신 리서치 brief 톤 검증."""
    qs = forcing_questions_korean()
    full_text = " ".join(q["question"] for q in qs)
    # 리서치 톤 키워드는 있어야
    assert "알아내고" in full_text or "알고" in full_text  # 무엇을 알아내고
    assert "어디에 쓰" in full_text or "목적" in full_text or "용도" in full_text  # 왜
    assert "도메인" in full_text or "맥락" in full_text  # 맥락
    assert "출처" in full_text or "신뢰도" in full_text  # 품질
    # 스타트업 비즈니스 톤 키워드는 없어야 (재사용된 텍스트면 잔재 점검)
    assert "10-star" not in full_text
    assert "Scope Expansion" not in full_text or "비교" in full_text  # alternatives 톤 잔재 X


def test_quick_clarification_max_two():
    qs = quick_clarification_questions(["timeframe", "domain", "evaluation"])
    assert len(qs) <= 2
    assert all("question" in q for q in qs)


def test_quick_clarification_filters_unknown_dims():
    qs = quick_clarification_questions(["unknown_dim", "timeframe"])
    # unknown_dim은 무시되고 timeframe만
    assert len(qs) == 1
    assert "시점" in qs[0]["question"]


# ---------------------------------------------------------------------------
# Phase 0c 진입 — merge_answers
# ---------------------------------------------------------------------------
def test_merge_answers_combines_qa_into_text():
    text = merge_answers_to_text(
        "MIRIVA 가격 책정",
        [
            {"id": "Q1_pain_root", "answer": "투자자 미팅 임박, 가격 결정 미뤄짐"},
            {"id": "Q3_implicit_caps", "answer": "한국 농가 grounding + 정량 ROI"},
            {"id": "Q5_alternatives", "answer": "Hold Scope"},
        ],
    )
    assert "[원 요청]" in text
    assert "MIRIVA" in text
    assert "[Q1_pain_root]" in text
    assert "투자자" in text
    assert "Hold Scope" in text


def test_merge_answers_skips_empty():
    text = merge_answers_to_text(
        "test",
        [
            {"id": "Q1", "answer": ""},
            {"id": "Q2", "answer": "actual"},
        ],
    )
    assert "[Q1]" not in text
    assert "[Q2] actual" in text


# ---------------------------------------------------------------------------
# Phase 0c, 0d — review formatters
# ---------------------------------------------------------------------------
def test_format_designdoc_review_markdown():
    doc = OfficeHours().reframe("MIRIVA 진단키트 가격 책정")
    md = format_designdoc_review(doc)
    assert "DesignDoc Review" in md
    assert "Phase 0c" in md
    assert "✅" in md and "✏️" in md and "❌" in md


def test_format_consensusplan_review_markdown():
    doc = OfficeHours().reframe("MIRIVA 진단키트 가격 책정")
    plan = PlanReview().autoplan(doc)
    md = format_consensusplan_review(plan)
    assert "ConsensusPlan Review" in md
    assert "Phase 0d" in md
    assert "consensus_score" not in md  # 텍스트 그대로 안 나오고 fmt
    assert "Consensus" in md
    assert "CEO" in md


# ---------------------------------------------------------------------------
# Phase 0e — Mode Routing
# ---------------------------------------------------------------------------
def test_route_mode_autonomous_loop_for_continuous_keywords():
    """지속/장기/매일 키워드 → autonomous_loop."""
    user = "AgTech 트렌드를 매일 지속적으로 모니터링하면서 vault에 쌓아가고 싶어"
    doc = OfficeHours().reframe(user)
    plan = PlanReview().autoplan(doc)
    decision = route_mode(doc, plan, user)
    assert decision.mode == "autonomous_loop"
    assert decision.confidence > 0.5
    assert "장기" in decision.reason or "vault" in decision.reason.lower() or "auto" in decision.reason.lower()


def test_route_mode_targeted_for_one_shot_keywords():
    """이번 한 번 / 결과 받기 키워드 → targeted_iterative."""
    user = "MIRIVA 가격 책정 이번 한 번 결과 받기 — 결론 주세요"
    doc = OfficeHours().reframe(user)
    plan = PlanReview().autoplan(doc)
    decision = route_mode(doc, plan, user)
    assert decision.mode == "targeted_iterative"
    assert decision.confidence > 0.5


def test_route_mode_default_targeted_when_ambiguous():
    """모호한 입력 → default targeted_iterative (저비용 fallback)."""
    user = "AI 에이전트 알려줘"
    doc = OfficeHours().reframe(user)
    plan = PlanReview().autoplan(doc)
    decision = route_mode(doc, plan, user)
    # default는 targeted (안전한 첫 진입)
    assert decision.mode == "targeted_iterative"


def test_route_mode_signals_present():
    user = "지속 모니터링 매일"
    doc = OfficeHours().reframe(user)
    plan = PlanReview().autoplan(doc)
    decision = route_mode(doc, plan, user)
    assert "monitoring_keywords" in decision.signals
    assert "specificity_keywords" in decision.signals


def test_format_mode_routing_decision_markdown():
    decision = ModeDecision(
        mode="autonomous_loop",
        reason="지속/장기 신호 강함",
        confidence=0.75,
        signals={"monitoring_keywords": 3, "specificity_keywords": 0,
                 "ceo_mode_bonus_auto": 2, "ceo_mode_bonus_targeted": 0},
    )
    md = format_mode_routing_decision(decision)
    assert "Mode Routing" in md
    assert "Phase 0e" in md
    assert "Autonomous Loop" in md
    assert "0.75" in md
    assert "✅" in md and "✏️" in md
