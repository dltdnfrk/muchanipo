"""Interview Prompts (Phase 0a~0e) 테스트."""

from src.intent.interview_prompts import (
    InterviewPlan,
    ModeDecision,
    assess,
    build_question_options,
    classify_research_type,
    forcing_questions_korean,
    quick_clarification_questions,
    merge_answers_to_text,
    format_designdoc_review,
    format_consensusplan_review,
    route_mode,
    format_mode_routing_decision,
    select_next_question,
    planning_question_contract,
)
from src.intent.interview_rubric import InterviewRubric
from src.intent.office_hours import OfficeHours, reframe_with_context
from src.intent.plan_review import PlanReview


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
    """Socratic ontology extraction keeps the six internal slots but not fixed PRD form copy."""
    qs = forcing_questions_korean()
    assert len(qs) == 6
    ids = [q["id"] for q in qs]
    assert "Q1_research_question" in ids  # 무엇을
    assert "Q2_purpose" in ids            # 왜
    assert "Q3_context" in ids            # 맥락
    assert "Q4_known" in ids              # 이미 아는 것
    assert "Q5_deliverable" in ids        # 산출물 형태
    assert "Q6_quality" in ids            # 품질 기준


def test_forcing_questions_use_ontology_extraction_tone_not_generic_prd_form():
    """Visible interview copy should push on ontology, not generic PRD/decision form slots."""
    qs = forcing_questions_korean()
    full_text = " ".join(q["question"] for q in qs)
    assert "핵심 개체" in full_text
    assert "행위자" in full_text
    assert "트리거" in full_text or "신호" in full_text
    assert "관계" in full_text
    assert "제외 의미" in full_text
    assert "반례" in full_text
    assert "PRD 개요" not in full_text
    assert "핵심 가치" not in full_text
    assert "요구사항→기능→상세기능" not in full_text
    assert "어떤 결정이나 산출물" not in full_text
    assert "답을 얻은 뒤 무엇을 결정" not in full_text
    # 스타트업 비즈니스 톤 키워드는 없어야 (재사용된 텍스트면 잔재 점검)
    assert "10-star" not in full_text
    assert "Scope Expansion" not in full_text or "비교" in full_text  # alternatives 톤 잔재 X


def test_planning_question_contract_maps_all_six_questions():
    contract = planning_question_contract()
    assert [item["id"] for item in contract] == [
        "Q1_research_question",
        "Q2_purpose",
        "Q3_context",
        "Q4_known",
        "Q5_deliverable",
        "Q6_quality",
    ]
    targets = {item["planning_target"] for item in contract}
    assert "prd.overview" in targets
    assert "feature_hierarchy" in targets
    assert "prd.success_metrics" in targets
    labels = " ".join(item["label"] for item in contract)
    assert "핵심 개체" in labels
    assert "해석 경계" in labels
    assert "증거 경계" in labels
    assert "PRD 개요" not in labels
    assert "핵심 가치" not in labels
    assert "요구사항→기능→상세기능" not in labels


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


# ---------------------------------------------------------------------------
# C22-B — Type classification + entropy ordering + dynamic options
# ---------------------------------------------------------------------------
def test_classify_type_comparative():
    assert classify_research_type("LangGraph vs CrewAI 비교") == "comparative"
    assert classify_research_type("A 또는 B 선택") == "comparative"


def test_classify_type_predictive():
    assert classify_research_type("작물 병원체 프로브 파운드리 구축하고 싶어") == "predictive"
    assert classify_research_type("PoC 만들고 feasibility 확인") == "predictive"


def test_classify_type_analytical():
    assert classify_research_type("MIRIVA ROI 정량 분석") == "analytical"
    assert classify_research_type("왜 churn이 높은지 원인") == "analytical"


def test_classify_type_exploratory_default():
    assert classify_research_type("AI 알려줘") == "exploratory"
    assert classify_research_type("") == "exploratory"


def test_assess_includes_research_type():
    plan = assess("MIRIVA 가격 정량 ROI 분석")
    assert plan.research_type == "analytical"


def test_select_next_question_picks_first_uncovered():
    r = InterviewRubric(topic="x")
    nxt = select_next_question(r)
    assert nxt is not None
    assert nxt.dimension_id == "Q1_research_question"
    r.update("Q1_research_question", "답변", quality=0.9)
    nxt2 = select_next_question(r)
    assert nxt2 is not None
    assert nxt2.dimension_id == "Q2_purpose"


def test_select_next_question_returns_none_when_all_covered():
    r = InterviewRubric(topic="x")
    for item in r.items:
        r.update(item.dimension_id, "답변", quality=0.9)
    assert select_next_question(r) is None


def test_q6_options_always_source_quality_a_to_d():
    opts = build_question_options("Q6_quality", "MIRIVA 가격")
    labels = [o["label"] for o in opts]
    assert any("A급" in l for l in labels)
    assert any("B급" in l for l in labels)
    assert any("C급" in l for l in labels)
    assert any("D급" in l for l in labels)
    assert opts[-1]["label"] == "Other"


def test_q3_options_stay_general_for_vertical_topics():
    opts = build_question_options("Q3_context", "MIRIVA 진단키트 한국 농가")
    labels = " ".join(o["label"] for o in opts)
    assert "농" not in labels
    assert "작물" not in labels
    assert "프로브" not in labels
    assert "자율과학" not in labels
    assert "특정 산업·제품 한정" in labels
    assert opts[-1]["label"] == "Other"


def test_question_options_do_not_hardcode_agriculture_market_vertical():
    topic = "딸기 농가용 저비용 분자진단 키트 시장성"
    for dim_id in ("Q1_research_question", "Q2_purpose", "Q3_context"):
        framed = reframe_with_context(dim_id, topic, {})
        combined = framed["question"] + " " + " ".join(
            f"{option['label']} {option['description']}" for option in framed["options"]
        )
        assert "농가 구매" not in combined
        assert "현장 workflow" not in combined
        assert "유통/사업화" not in combined
        assert "작물" not in combined


def test_interview_questions_are_topic_specific_for_ontology_request():
    topic = "데이터 사이언스 분야에서의 온톨로지"
    framed_q1 = reframe_with_context("Q1_research_question", topic, {})
    q1_text = framed_q1["question"]
    q1_options = " ".join(o["label"] for o in framed_q1["options"])
    assert "온톨로지" in q1_text
    assert "데이터 사이언스" in q1_text
    assert "제품 정의" not in q1_options
    assert "핵심 질문 좁히기" in q1_options

    framed_q4 = reframe_with_context(
        "Q4_known",
        topic,
        {"purpose": "학습·이해", "context": "데이터 사이언스 / 지식 그래프 맥락"},
    )
    q4_text = framed_q4["question"]
    assert "데이터 사이언스" in q4_text
    assert "온톨로지" in q4_text
    assert "이미 알고" in q4_text


def test_reframe_questions_avoid_generic_prd_decision_form_copy():
    topic = "노인 1인 가구 재택의료 신청 실패 원인"
    banned = (
        "PRD 개요",
        "핵심 가치는",
        "답을 얻으면 무엇을 결정",
        "어떤 결정이나 산출물",
        "요구사항→기능→상세기능",
        "원하는 산출물 형태",
    )
    for dim_id in (
        "Q1_research_question",
        "Q2_purpose",
        "Q3_context",
        "Q4_known",
        "Q5_deliverable",
        "Q6_quality",
    ):
        framed = reframe_with_context(dim_id, topic, {})
        text = framed["question"] + " " + " ".join(
            f"{option['label']} {option['description']}" for option in framed["options"]
        )
        assert all(pattern not in text for pattern in banned), (dim_id, text)
    q2 = reframe_with_context("Q2_purpose", topic, {})["question"]
    assert "서로 다른 해석" in q2
    q5 = reframe_with_context("Q5_deliverable", topic, {})["question"]
    assert "개념 지도" in q5 or "엔티티" in q5


def test_interview_questions_embed_topic_without_vertical_preset_for_market_request():
    topic = "딸기 농가용 저비용 분자진단 키트 시장성"
    framed = reframe_with_context("Q2_purpose", topic, {})
    text = framed["question"]
    labels = " ".join(o["label"] for o in framed["options"])
    assert "딸기" in text or "분자진단" in text
    assert "농가 구매" not in labels
    assert "가격" not in labels
    assert "구매" not in labels


def test_q5_options_describe_ontology_maps_not_requirement_tree():
    opts = build_question_options("Q5_deliverable", "any topic")
    labels = " ".join(o["label"] for o in opts)
    assert "Obsidian" in labels or "vault" in labels.lower()
    assert "Entity" in labels or "Relation" in labels
    assert "Requirement" not in labels and "Feature" not in labels
    assert "Evidence" in labels or "증거" in labels
    assert opts[-1]["label"] == "Other"


def test_format_mode_routing_decision_markdown():
    decision = ModeDecision(
        mode="autonomous_loop",
        reason="지속/장기 신호 강함",
        confidence=0.75,
        signals={"monitoring_keywords": 3, "specificity_keywords": 0,
                 "ceo_mode_bonus_auto": 2, "ceo_mode_bonus_targeted": 0,
                 "research_type_bonus_auto": 0, "research_type_bonus_targeted": 0},
    )
    md = format_mode_routing_decision(decision)
    assert "Mode Routing" in md
    assert "Phase 0e" in md
    assert "Autonomous Loop" in md
    assert "0.75" in md
    assert "✅" in md and "✏️" in md


# ---------------------------------------------------------------------------
# C23-B — Type-aware Phase 0e routing
# ---------------------------------------------------------------------------
def _baseline_decision(user: str, **kwargs):
    """test helper — OfficeHours/PlanReview 통과해 route_mode 호출."""
    doc = OfficeHours().reframe(user)
    plan = PlanReview().autoplan(doc)
    return route_mode(doc, plan, user, **kwargs)


def test_route_mode_analytical_biases_targeted():
    """analytical → targeted_iterative 보너스, signals에 research_type_bonus_targeted=1."""
    user = "MIRIVA churn 원인 정량 분석"  # analytical 키워드 포함
    decision = _baseline_decision(user)
    assert decision.research_type == "analytical"
    assert decision.signals.get("research_type_bonus_targeted") == 1
    assert decision.signals.get("research_type_bonus_auto") == 0
    assert decision.mode == "targeted_iterative"


def test_route_mode_comparative_biases_targeted():
    """comparative → targeted_iterative 보너스."""
    user = "LangGraph vs CrewAI 어느 게 더 적합"  # comparative
    decision = _baseline_decision(user)
    assert decision.research_type == "comparative"
    assert decision.signals.get("research_type_bonus_targeted") == 1
    assert decision.mode == "targeted_iterative"


def test_route_mode_predictive_biases_autonomous():
    """predictive → autonomous_loop 보너스, monitoring 신호와 합쳐 auto 우세."""
    # 동일 monitoring 텍스트로 baseline vs predictive override 비교 — type bonus 효과 검증
    user = "작물 병원체 프로브 매일 지속 모니터링하면서 꾸준히 trend feed"
    base = _baseline_decision(user, research_type="exploratory")
    pred = _baseline_decision(user, research_type="predictive")
    assert pred.research_type == "predictive"
    assert pred.signals.get("research_type_bonus_auto") == 1
    assert pred.signals.get("research_type_bonus_targeted") == 0
    # predictive 보너스 1 더해진 만큼 auto 쪽이 baseline 대비 약하지 않음
    assert (
        pred.signals["research_type_bonus_auto"] - pred.signals["research_type_bonus_targeted"]
    ) > (
        base.signals["research_type_bonus_auto"] - base.signals["research_type_bonus_targeted"]
    )
    assert pred.mode == "autonomous_loop"


def test_route_mode_exploratory_neutral():
    """exploratory → 보너스 0, 기존 휴리스틱만 작동."""
    user = "AI 에이전트 알려줘"  # exploratory default
    decision = _baseline_decision(user)
    assert decision.research_type == "exploratory"
    assert decision.signals.get("research_type_bonus_auto") == 0
    assert decision.signals.get("research_type_bonus_targeted") == 0


def test_route_mode_explicit_research_type_overrides():
    """research_type 인자 명시 시 자동 분류 무시."""
    user = "그냥 알려줘"
    decision = _baseline_decision(user, research_type="predictive")
    assert decision.research_type == "predictive"
    assert decision.signals.get("research_type_bonus_auto") == 1


def test_format_mode_routing_decision_shows_type():
    """format에 research_type 한 줄 표시."""
    decision = ModeDecision(
        mode="targeted_iterative",
        reason="analytical 단발",
        confidence=0.7,
        signals={"monitoring_keywords": 0, "specificity_keywords": 1,
                 "ceo_mode_bonus_auto": 0, "ceo_mode_bonus_targeted": 1,
                 "research_type_bonus_auto": 0, "research_type_bonus_targeted": 1},
        research_type="analytical",
    )
    md = format_mode_routing_decision(decision)
    assert "research_type" in md
    assert "Analytical" in md or "analytical" in md
