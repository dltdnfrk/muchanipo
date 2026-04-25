"""Office Hours (THINK 단계) 테스트."""

from src.intent.office_hours import (
    Alternative,
    DesignDoc,
    OfficeHours,
    PreScreenResult,
    pre_screen_hook,
    reframe_with_context,
)


def test_reframe_basic_design_doc_shape():
    oh = OfficeHours()
    doc = oh.reframe("MIRIVA 진단키트 가격 책정 어떻게 해야 하는가?")
    assert isinstance(doc, DesignDoc)
    assert doc.raw_input.startswith("MIRIVA")
    assert doc.pain_root  # 6 forcing question 1 — 비어있지 않아야
    assert doc.contrary_framing
    assert isinstance(doc.implicit_capabilities, list) and len(doc.implicit_capabilities) >= 1
    assert isinstance(doc.challenged_premises, list) and len(doc.challenged_premises) >= 1
    assert len(doc.alternatives) == 3  # Hold / Expansion / Reduction
    assert doc.effort_map_summary


def test_surface_pattern_detection_pain_root():
    oh = OfficeHours()
    doc = oh.reframe("LangGraph vs CrewAI 뭐가 좋아?")
    # SURFACE_PATTERNS의 "뭐가 좋아"가 트리거돼야
    assert "뭐가 좋아" in doc.pain_root or "선택지 비교" in doc.pain_root


def test_implicit_capabilities_korean_domain():
    """한국/AgTech 키워드가 들어오면 Korea grounding 능력이 추출되어야."""
    oh = OfficeHours()
    doc = oh.reframe("한국 AgTech 농가 대상 진단키트 가격은 얼마가 적정한가?")
    caps_joined = " ".join(doc.implicit_capabilities)
    assert "한국" in caps_joined or "Nemotron" in caps_joined


def test_implicit_capabilities_research_grounding():
    oh = OfficeHours()
    doc = oh.reframe("최신 AI agent 평가 방법 리서치 분석해줘")
    caps_joined = " ".join(doc.implicit_capabilities)
    # "최신" → 시점 정의 / "리서치/분석" → citation grounding
    assert "시점" in caps_joined or "freshness" in caps_joined.lower()
    assert "citation" in caps_joined.lower() or "출처" in caps_joined


def test_challenge_premises_strong_assertions():
    oh = OfficeHours()
    doc = oh.reframe("이 방법이 반드시 최선이라고 다들 말한다")
    challenges_joined = " ".join(doc.challenged_premises)
    # "반드시" + "다들" 둘 다 도전돼야
    assert "단정" in challenges_joined or "반례" in challenges_joined
    assert "표본" in challenges_joined or "모두" in challenges_joined


def test_alternatives_have_three_modes():
    oh = OfficeHours()
    doc = oh.reframe("아무 토픽이나 넣어보자")
    titles = [a.title for a in doc.alternatives]
    assert any("Hold" in t for t in titles)
    assert any("Expansion" in t for t in titles)
    assert any("Reduction" in t for t in titles)


def test_to_brief_outputs_markdown_with_all_sections():
    oh = OfficeHours()
    doc = oh.reframe("test 토픽")
    brief = doc.to_brief()
    assert "# Design Doc" in brief
    assert "## Pain Root" in brief
    assert "## Contrary Framing" in brief
    assert "## Implicit Capabilities" in brief
    assert "## Alternatives" in brief
    assert "## Effort Summary" in brief


def test_empty_input_raises():
    oh = OfficeHours()
    try:
        oh.reframe("   ")
    except ValueError as e:
        assert "empty" in str(e).lower()
    else:
        assert False, "ValueError 기대"


def test_aup_risk_field_present_when_lockdown_available():
    """lockdown이 있으면 risk score가 0.0~1.0 범위로 채워져야."""
    oh = OfficeHours()
    doc = oh.reframe("정상적인 리서치 토픽")
    # lockdown 부재 시 0.0, 있으면 0.0 이상의 float
    assert isinstance(doc.aup_risk_score, float)
    assert 0.0 <= doc.aup_risk_score <= 1.0


# ---------------------------------------------------------------------------
# C22-C — pre_screen_hook + reframe_with_context
# ---------------------------------------------------------------------------
def test_pre_screen_detects_unknown_acronym():
    res = pre_screen_hook("MIRIVA 진단키트 가격 책정")
    assert res.need_clarification is True
    assert "MIRIVA" in res.detected_terms


def test_pre_screen_skips_known_acronyms():
    res = pre_screen_hook("AI 에이전트 ROI 분석")
    assert res.need_clarification is False
    assert res.detected_terms == []


def test_pre_screen_skips_if_already_clarified():
    history = [{"role": "assistant", "content": "MIRIVA 명확화 — 진단키트 제품명"}]
    res = pre_screen_hook("MIRIVA 가격 책정", history=history)
    assert res.need_clarification is False
    assert "ABSOLUTELY NECESSARY" in res.reason or "재질문 억제" in res.reason


def test_pre_screen_no_acronym_no_clarification():
    res = pre_screen_hook("한국 농가 가격 분석")
    assert res.need_clarification is False


def test_reframe_returns_question_and_options():
    out = reframe_with_context("Q1_research_question", "MIRIVA 가격")
    assert out["dim_id"] == "Q1_research_question"
    assert "알아내고" in out["question"] or out["question"]
    assert isinstance(out["options"], list) and len(out["options"]) >= 2
    assert out["options"][-1]["label"] == "Other"


def test_reframe_uses_prev_answers_q4():
    out = reframe_with_context(
        "Q4_known",
        "MIRIVA 가격",
        prev_answers={"Q3_context": "한국 사과 농가"},
    )
    assert "한국 사과 농가" in out["question"]


def test_reframe_uses_prev_answers_q5():
    out = reframe_with_context(
        "Q5_deliverable",
        "MIRIVA 가격",
        prev_answers={"Q2_purpose": "투자자 IR"},
    )
    assert "투자자 IR" in out["question"]


def test_reframe_q6_options_source_quality():
    out = reframe_with_context("Q6_quality", "any topic")
    labels = [o["label"] for o in out["options"]]
    assert any("A급" in l for l in labels)
    assert any("D급" in l for l in labels)
