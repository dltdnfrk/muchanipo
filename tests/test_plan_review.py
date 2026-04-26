"""Plan Review (PLAN 단계) 테스트."""

from src.intent.office_hours import OfficeHours
from src.intent.plan_review import (
    PlanReview, CeoReview, EngReview, DesignReview, DevexReview, ConsensusPlan,
)


def _doc(text="MIRIVA 진단키트 가격 책정 어떻게 해야 하는가?"):
    return OfficeHours().reframe(text)


def test_ceo_review_modes():
    pr = PlanReview()
    review = pr.ceo_review(_doc())
    assert review.mode in {"expansion", "selective", "hold", "reduction"}
    assert review.ten_star_vision
    assert review.strategic_fit
    assert isinstance(review.opt_in_decisions, list) and len(review.opt_in_decisions) >= 1
    assert 0.0 <= review.confidence <= 1.0


def test_eng_review_locks_architecture():
    pr = PlanReview()
    doc = _doc()
    eng = pr.eng_review(doc, ceo=pr.ceo_review(doc))
    assert eng.architecture_summary
    assert len(eng.data_flow) >= 5
    assert len(eng.state_transitions) >= 3
    assert len(eng.edge_cases) >= 3
    assert eng.feasibility in {"easy", "medium", "hard", "blocked"}


def test_design_review_user_journey():
    pr = PlanReview()
    review = pr.design_review(_doc())
    assert len(review.user_journey) >= 5
    assert len(review.ux_principles) >= 3
    assert review.visual_coherence


def test_devex_review_friction_and_debugability():
    pr = PlanReview()
    doc = _doc()
    eng = pr.eng_review(doc)
    devex = pr.devex_review(doc, eng=eng)
    assert len(devex.friction_points) >= 3
    assert 0.0 <= devex.debuggability_score <= 1.0
    assert len(devex.observability_gaps) >= 2


def test_autoplan_passes_gate_for_normal_input():
    pr = PlanReview()
    doc = _doc("MIRIVA 진단키트 가격 책정 어떻게 해야 하는가?")
    plan = pr.autoplan(doc)
    assert isinstance(plan, ConsensusPlan)
    assert plan.gate_passed is True or plan.consensus_score >= 0.5
    assert plan.consensus_score > 0.0
    # ontology_seed가 council 입력 형식
    onto = plan.to_ontology()
    assert "roles" in onto
    assert "intents" in onto
    assert "value_axes" in onto
    assert "design_doc_brief" in onto


def test_autoplan_korean_domain_adds_agtech_farmer_role():
    pr = PlanReview()
    doc = _doc("한국 AgTech 농가 대상 진단키트 가격은 얼마가 적정한가?")
    plan = pr.autoplan(doc)
    assert "agtech_farmer" in plan.ontology_seed["roles"]


def test_autoplan_comparison_question_adds_comparison_judge():
    pr = PlanReview()
    doc = _doc("LangGraph vs CrewAI 뭐가 좋아?")
    plan = pr.autoplan(doc)
    assert "comparison_judge" in plan.ontology_seed["roles"]


def test_autoplan_consensus_threshold_blocks_low_signal():
    """consensus_threshold를 매우 높게 잡으면 모든 입력이 gate 차단됨."""
    pr = PlanReview(consensus_threshold=0.99)
    doc = _doc()
    plan = pr.autoplan(doc)
    assert plan.gate_passed is False
    assert "consensus" in plan.gate_reason


def test_value_axes_match_ceo_mode():
    """expansion 모드면 innovation_orientation이 더 높아야."""
    pr = PlanReview()
    doc = OfficeHours().reframe(
        "최신 AI agent 평가 방법 한국 농가 도메인에서 비교 분석해줘 반드시"
    )
    plan = pr.autoplan(doc)
    axes = plan.ontology_seed["value_axes"]
    assert axes["innovation_orientation"] >= 0.4
    assert axes["time_horizon"] in {"short", "mid", "long"}
    assert 0.0 <= axes["risk_tolerance"] <= 1.0


# ---------------------------------------------------------------------------
# C22-D — rubric_coverage_gate
# ---------------------------------------------------------------------------
from src.intent.interview_rubric import InterviewRubric
from src.intent.plan_review import rubric_coverage_gate


def _rubric_with_n_covered(n: int) -> InterviewRubric:
    r = InterviewRubric(topic="x")
    for i, item in enumerate(r.items):
        if i < n:
            r.update(item.dimension_id, "ok", quality=0.9)
    return r


def test_coverage_gate_passes_at_threshold():
    r = _rubric_with_n_covered(5)  # 5/6 = 0.833 ≥ 0.75
    passed, reason = rubric_coverage_gate(r, threshold=0.75)
    assert passed is True
    assert "0.83" in reason or "OK" in reason


def test_coverage_gate_passes_full_coverage():
    r = _rubric_with_n_covered(6)
    passed, reason = rubric_coverage_gate(r)
    assert passed is True


def test_coverage_gate_fails_below_threshold():
    r = _rubric_with_n_covered(4)  # 4/6 = 0.666 < 0.75
    passed, reason = rubric_coverage_gate(r, threshold=0.75)
    assert passed is False
    assert "추가 probe" in reason


def test_coverage_gate_reports_uncovered_dims():
    r = _rubric_with_n_covered(3)
    passed, reason = rubric_coverage_gate(r)
    assert passed is False
    assert "Q4_known" in reason or "Q5_deliverable" in reason or "Q6_quality" in reason


def test_coverage_gate_zero_initial():
    r = InterviewRubric(topic="x")
    passed, reason = rubric_coverage_gate(r, threshold=0.5)
    assert passed is False
    assert "0.00" in reason
