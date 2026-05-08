from __future__ import annotations

import pytest

from src.interview.brief import ResearchBrief
from src.research.planner import ResearchPlan, ResearchPlanner
from src.pipeline.idea_to_council import IdeaToCouncilPipeline, _extract_original_topic_anchor
from src.hitl.plannotator_adapter import HITLAdapter
from src.research.runner import MockResearchRunner
from src.research.karpathy_autoresearch import KarpathyAutoresearchRunner
from src.intake.normalizer import capture_idea
from src.interview.session import InterviewSession
from src.intent.office_hours import OfficeHours


GENERAL_TOPIC = "저비용 분자진단 키트 시장성 source-backed Deep Research council persona 검증 3"
STALE_TOPIC = "온톨로지 데이터 추출 기반 대사체 적용 사례"
REQUIRED_TOKENS = ["저비용", "분자진단", "키트", "시장성"]


def test_extract_original_topic_anchor_ignores_stale_embedded_interview_answers() -> None:
    merged = "\n".join(
        [
            f"[원 요청] {GENERAL_TOPIC}",
            f"[Q1_research_question] {STALE_TOPIC}",
            "[Q2_purpose] 핵심 정의와 범위, 데이터 추출 방법을 조사",
        ]
    )

    assert _extract_original_topic_anchor(merged) == GENERAL_TOPIC


def test_research_planner_preserves_original_korean_topic_anchor_tokens() -> None:
    brief = ResearchBrief(
        raw_idea=f"[원 요청] {GENERAL_TOPIC}\n[Q1_research_question] {STALE_TOPIC}",
        research_question=STALE_TOPIC,
        purpose="research_report",
        context="핵심 정의와 범위, 데이터 추출 방법",
        coverage_score=1.0,
        original_topic=GENERAL_TOPIC,
    )
    plan = ResearchPlanner().plan(brief, max_queries=4)
    first_query = plan.queries[0]

    for token in REQUIRED_TOKENS:
        assert token in first_query
    assert STALE_TOPIC not in first_query
    assert any("official statistics peer reviewed evidence" in query for query in plan.queries[1:])


def test_research_planner_adds_live_search_bridge_queries_without_replacing_anchor() -> None:
    brief = ResearchBrief(
        raw_idea=GENERAL_TOPIC,
        research_question=STALE_TOPIC,
        purpose="research_report",
        context="구매자, 유통 채널, 규제, 가격 지불의사",
        coverage_score=1.0,
        original_topic=GENERAL_TOPIC,
    )

    plan = ResearchPlanner().plan(brief, max_queries=8)

    assert plan.queries[0] == GENERAL_TOPIC
    joined = "\n".join(plan.queries[1:]).casefold()
    for token in ("molecular diagnostic", "kit", "low cost", "market adoption", "pricing"):
        assert token in joined


def test_research_planner_prioritizes_translated_bridge_inside_small_live_query_budget() -> None:
    brief = ResearchBrief(
        raw_idea=GENERAL_TOPIC,
        research_question=STALE_TOPIC,
        purpose="research_report",
        context="구매자, 유통 채널, 규제, 가격 지불의사",
        coverage_score=1.0,
        original_topic=GENERAL_TOPIC,
    )

    plan = ResearchPlanner().plan(brief, max_queries=7)

    assert plan.queries[0] == GENERAL_TOPIC
    assert any("molecular diagnostic" in query.casefold() for query in plan.queries[1:])
    assert any("market adoption" in query.casefold() for query in plan.queries[1:])



def test_translated_bridge_queries_cover_market_and_regional_adoption_evidence_intents() -> None:
    from src.research.queries import translated_topic_queries

    queries = translated_topic_queries(GENERAL_TOPIC)
    joined = "\n".join(queries).casefold()

    assert "government statistics" in joined or "official statistics" in joined
    assert "규제" in joined or "regulatory" in joined
    english_queries = [query for query in queries if "공식 통계" not in query]
    assert all("molecular diagnostic" in query.casefold() for query in english_queries)


def test_translated_bridge_queries_do_not_inject_vertical_defaults_for_generic_regional_market_topics() -> None:
    from src.research.queries import translated_topic_queries

    queries = translated_topic_queries("Korea home healthcare SaaS market adoption pricing")
    joined = "\n".join(queries).casefold()

    assert "korea" in joined
    assert "government statistics" in joined
    assert "distribution channel" in joined
    assert "regulatory adoption" in joined
    assert "agricultural statistics" not in joined
    assert "farmer willingness" not in joined



def test_translated_bridge_queries_route_concise_market_topics_to_source_channels() -> None:
    from src.research.queries import translated_topic_queries

    queries = translated_topic_queries("B2B SaaS 가격 도입")
    joined = "\n".join(queries).casefold()

    assert queries[0] == "B2B SaaS 가격 도입"
    assert "government statistics" in joined
    assert "willingness to pay" in joined
    assert "market adoption" in joined
    assert "agricultural statistics" not in joined



def test_translated_bridge_queries_do_not_route_financial_asset_markets_to_product_source_channels() -> None:
    from src.research.queries import translated_topic_queries

    for query in (
        "financial market adoption pricing SaaS",
        "cryptocurrency pricing adoption",
        "bond market adoption pricing",
        "forex market pricing adoption",
    ):
        queries = translated_topic_queries(query)
        joined = "\n".join(queries).casefold()

        assert "government statistics" not in joined
        assert "willingness to pay" not in joined
        assert "market adoption" not in joined



def test_translated_bridge_queries_still_route_product_market_forecast_to_source_channels() -> None:
    from src.research.queries import translated_topic_queries

    queries = translated_topic_queries("제품 도입 후 시장 예측 B2B SaaS 가격")
    joined = "\n".join(queries).casefold()

    assert queries[0] == "제품 도입 후 시장 예측 B2B SaaS 가격"
    assert "government statistics" in joined
    assert "willingness to pay" in joined
    assert "market adoption" in joined



def test_research_planner_prioritizes_regional_market_bridge_inside_live_query_budget() -> None:
    brief = ResearchBrief(
        raw_idea=GENERAL_TOPIC,
        research_question=STALE_TOPIC,
        purpose="research_report",
        context="구매자, 유통 채널, 규제, 가격 지불의사",
        coverage_score=1.0,
        original_topic=GENERAL_TOPIC,
    )

    plan = ResearchPlanner().plan(brief, max_queries=8)
    joined = "\n".join(plan.queries).casefold()

    assert "government statistics" in joined or "official statistics" in joined
    assert "규제" in joined or "regulatory" in joined


def test_research_planner_keeps_local_diagnostic_market_retry_in_seven_query_budget() -> None:
    """Verification 18b fixed scientific recall but trimmed the local market retry.

    The seven-query source-backed budget must keep one scientific DOI/assay
    probe and a second local market/source-channel probe, without evicting the
    generic government/WTP adoption probe.
    """

    topic = "저비용 분자진단 키트 시장성 source-backed Deep Research council persona 검증 19"
    brief = ResearchBrief(
        raw_idea=topic,
        research_question=topic,
        purpose="research_report",
        context="구매자, 유통 채널, 규제, 가격 지불의사",
        coverage_score=1.0,
        original_topic=topic,
    )

    plan = ResearchPlanner().plan(brief, max_queries=7)
    joined = "\n".join(plan.queries).casefold()

    assert "peer reviewed doi assay review lamp pcr biosensor" in joined
    assert "government statistics willingness to pay adoption market adoption" in joined



def test_research_planner_spends_tight_live_budget_on_market_and_local_adoption_probe() -> None:
    """Verification 10D used a 4-query shallow/source run and trimmed market/regional probes.

    The first English bridge query already carries scientific/field-validation terms,
    so the next scarce slot should probe the local market/adoption channel instead
    of another technical LAMP/PCR suffix.
    """
    brief = ResearchBrief(
        raw_idea=GENERAL_TOPIC,
        research_question=STALE_TOPIC,
        purpose="research_report",
        context="구매자, 유통 채널, 규제, 가격 지불의사",
        coverage_score=1.0,
        original_topic=GENERAL_TOPIC,
    )

    plan = ResearchPlanner().plan(brief, max_queries=4)
    joined = "\n".join(plan.queries).casefold()

    assert plan.queries[0] == GENERAL_TOPIC
    assert "molecular diagnostic" in joined
    assert "공식 통계 가격 도입 유통 규제" in joined
    assert "lamp pcr biosensor" not in joined



def test_translated_bridge_queries_add_local_language_source_channel_probe_before_long_english_market_probe() -> None:
    from src.research.queries import translated_topic_queries

    queries = translated_topic_queries(GENERAL_TOPIC)

    assert any("공식 통계 가격 도입 유통 규제" in query for query in queries)
    local_query = next(query for query in queries if "공식 통계 가격 도입 유통 규제" in query)
    assert "저비용" in local_query or "시장성" in local_query
    assert "분자진단" not in local_query
    assert "키트" not in local_query



def test_autoresearch_candidate_plans_keep_topic_anchor_telemetry() -> None:
    plan = ResearchPlan(
        brief_id="brief-test",
        queries=[GENERAL_TOPIC, "molecular diagnostic kit field validation pricing"],
        topic_anchor=GENERAL_TOPIC,
    )
    runner = KarpathyAutoresearchRunner(MockResearchRunner(), iteration_budget=4)

    candidates = runner._candidate_plans(plan)

    assert len(candidates) >= 2
    assert all(candidate.plan.topic_anchor == GENERAL_TOPIC for candidate in candidates)



def test_pipeline_brief_uses_original_topic_anchor_over_stale_interview_q1() -> None:
    merged = "\n".join(
        [
            f"[원 요청] {GENERAL_TOPIC}",
            f"[Q1_research_question] {STALE_TOPIC}",
            "[Q2_purpose] 시장성 검토",
            "[Q3_context] 구매자, 유통 채널, 규제, 가격 지불의사",
            "[Q4_known] 현장 검증과 분자진단 민감도/특이도가 중요",
            "[Q5_deliverable] source-backed PRD report",
            "[Q6_quality] 과학/진단, field_validation, market/pricing/adoption, regional_adoption facet 포함",
        ]
    )
    pipeline = IdeaToCouncilPipeline(
        hitl_adapter=HITLAdapter(timeout_seconds=0),
        research_runner=MockResearchRunner(),
        require_live=False,
    )
    idea = capture_idea(merged)
    interview = InterviewSession.from_idea(idea)
    design_doc = OfficeHours().reframe(merged)

    brief = pipeline._brief_from_interview(interview, merged, design_doc)
    plan = ResearchPlanner().plan(brief, max_queries=4)

    assert brief.original_topic == GENERAL_TOPIC
    for token in REQUIRED_TOKENS:
        assert token in plan.queries[0]
    assert STALE_TOPIC not in plan.queries[0]
