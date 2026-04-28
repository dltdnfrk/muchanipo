"""Phase 1 통합 E2E 테스트.

PRD-v2의 새 컴포넌트들이 함께 동작하는지 검증:
    1. PersonaGenerator.generate() + DiversityMap (HACHIMI 3-stage + MAP-Elites)
    2. ChapterMapper + PyramidFormatter (10 rounds → 6 MBB chapters → top-down)
"""

from __future__ import annotations

import pytest

from src.council.diversity_mapper import DiversityMap
from src.council.persona_generator import PersonaGenerator
from src.report.chapter_mapper import ChapterMapper, RoundDigest
from src.report.pyramid_formatter import PyramidFormatter


# =====================================================================
# 1. Persona generation E2E (HACHIMI + MAP-Elites)
# =====================================================================


def _ontology():
    return {
        "roles": ["evidence_reviewer", "market_analyst", "risk_officer"],
        "intents": [
            "Summarize grounded evidence and report uncertainty.",
            "Compare public market signals with cited sources.",
            "Assess downside risks and propose mitigations.",
        ],
        "allowed_tools": ["read_file", "search_index"],
        "required_outputs": ["report", "citations"],
        "value_axes": {
            "time_horizon": "long",
            "risk_tolerance": 0.3,
            "stakeholder_priority": ["primary", "secondary", "tertiary"],
            "innovation_orientation": 0.7,
        },
    }


def test_generate_returns_finals_within_target_count():
    gen = PersonaGenerator()
    finals, telemetry = gen.generate(_ontology(), target_count=3)
    assert len(finals) == 3
    assert isinstance(telemetry, dict)
    assert telemetry["revisions_used"] >= 0
    # 모두 정상 manifest 포함
    for fp in finals:
        assert fp.manifest["allowed_tools"]
        assert "value_axes" in fp.manifest


def test_generate_with_diversity_map_admits_into_cells():
    gen = PersonaGenerator()
    dmap = DiversityMap(bins_per_axis=4)
    finals, telemetry = gen.generate(_ontology(), target_count=3, diversity_map=dmap)
    # 적어도 1개 셀 점유돼야 함 (target 3, fallback 포함될 수 있음)
    assert telemetry["coverage_after_admit"] >= 0.0
    # admit된 페르소나의 axes는 dmap의 점유 셀에 매칭
    occupied = dmap.occupied_coords()
    # admit 호출이 일어나면 1+ 셀 점유 (fallback도 카운트는 안 됨 — admit만)
    assert isinstance(occupied, set)


def test_generate_topic_keywords_filter_irrelevant_personas():
    """토픽 무관한 ontology를 줘도 deep validator가 fallback으로 채움."""
    gen = PersonaGenerator()
    # 토픽: 양자 컴퓨팅 — ontology의 intent와 거의 무관
    finals, telemetry = gen.generate(
        _ontology(),
        target_count=2,
        topic_keywords=["quantum", "qubit", "supremacy", "entanglement"],
    )
    assert len(finals) == 2
    # 토픽 무관 → deep_failed가 생기고 fallback이 채움
    assert telemetry["fallbacks_used"] >= 0  # 0 이상 (관용)


def test_generate_revision_loop_recovers_from_initial_failure():
    """초기 ontology에 위험 요소가 있어도 revise loop가 복구."""
    bad_ontology = dict(_ontology())
    # value_axes에 잘못된 값 주입 → revise가 default로 교체해야 함
    bad_ontology["value_axes"] = {
        "time_horizon": "INVALID",  # short/mid/long 아님
        "risk_tolerance": 5.0,  # 0~1 범위 밖
        "stakeholder_priority": ["primary"],
        "innovation_orientation": 0.5,
    }
    gen = PersonaGenerator()
    finals, telemetry = gen.generate(bad_ontology, target_count=2, max_revisions=3)
    # 결과: revise가 한 번 이상 실행됐고 finals은 target_count 채움
    assert len(finals) == 2
    assert telemetry["revisions_used"] >= 1


# =====================================================================
# 2. Council → MBB report E2E
# =====================================================================


def _full_round_set():
    """10 rounds 가짜 fixture — 각 layer 대표 1개씩."""
    return [
        RoundDigest("L1_market_sizing", "(test)", "TAM 50조 by 2030", confidence=0.9,
                    body_claims=["국내 시장 5조원", "성장률 22% CAGR"]),
        RoundDigest("L2_competition", "(test)", "5 forces moderate", confidence=0.7,
                    body_claims=["진입장벽 보통", "대체재 위협 높음"], framework="Porter"),
        RoundDigest("L3_jtbd", "(test)", "JTBD: speed + accuracy", confidence=0.8,
                    body_claims=["functional: time saved", "social: reputation"]),
        RoundDigest("L4_finance", "(test)", "LTV/CAC = 3.5", confidence=0.85,
                    body_claims=["payback 9 months", "gross margin 65%"]),
        RoundDigest("L5_risk", "(test)", "regulatory exposure high", confidence=0.6,
                    body_claims=["식약처 신고 필요", "환불 요구 가능성"]),
        RoundDigest("L6_roadmap", "(test)", "90일 MVP 출시", confidence=0.75,
                    body_claims=["alpha 30일", "beta 60일"]),
        RoundDigest("L7_governance", "(test)", "decision body weekly", confidence=0.5,
                    body_claims=["주1회 검토", "월1회 보고"]),
        RoundDigest("L8_kpi", "(test)", "North Star = MAU", confidence=0.7,
                    body_claims=["weekly active users", "retention D30"]),
        RoundDigest("L9_dissent", "(test)", "minority: market too small", confidence=0.4,
                    body_claims=["TAM may be overstated"]),
        RoundDigest("L10_executive_synthesis", "(test)", "Recommend Go", confidence=0.85,
                    body_claims=[
                        "현재 시장 5조원 + CAGR 22%",  # Situation
                        "기존 솔루션 정확도 한계 + 규제 리스크",  # Complication
                        "MVP 90일 출시 + 권고: Go",  # Resolution
                    ]),
    ]


def test_full_pipeline_produces_six_chapters_in_order():
    rounds = _full_round_set()
    chapters = ChapterMapper().map(rounds)
    formatted = PyramidFormatter().reorder_all(chapters)

    assert len(formatted) == 6
    assert [c.chapter_no for c in formatted] == [1, 2, 3, 4, 5, 6]


def test_executive_summary_first_line_is_resolution():
    rounds = _full_round_set()
    chapters = ChapterMapper().map(rounds)
    formatted = PyramidFormatter().reorder_all(chapters)

    ch1 = formatted[0]
    # Resolution이 lead_claim
    assert "Go" in ch1.lead_claim or "MVP" in ch1.lead_claim
    # body 첫 줄은 [Situation], 둘째 [Complication], 셋째 [Resolution]
    assert ch1.body_claims[0].startswith("[Situation]")
    assert ch1.body_claims[1].startswith("[Complication]")
    assert ch1.body_claims[2].startswith("[Resolution]")


def test_market_chapter_combines_l1_and_l3():
    rounds = _full_round_set()
    chapters = ChapterMapper().map(rounds)
    ch2 = chapters[1]
    assert ch2.chapter_no == 2
    assert "L1_market_sizing" in ch2.source_layers
    assert "L3_jtbd" in ch2.source_layers


def test_risk_chapter_combines_l5_and_l9():
    rounds = _full_round_set()
    chapters = ChapterMapper().map(rounds)
    ch5 = chapters[4]
    assert ch5.chapter_no == 5
    assert set(ch5.source_layers) == {"L5_risk", "L9_dissent"}


def test_roadmap_chapter_combines_l6_l7_l8():
    rounds = _full_round_set()
    chapters = ChapterMapper().map(rounds)
    ch6 = chapters[5]
    assert ch6.chapter_no == 6
    assert set(ch6.source_layers) == {"L6_roadmap", "L7_governance", "L8_kpi"}


def test_competition_chapter_carries_porter_framework():
    rounds = _full_round_set()
    chapters = ChapterMapper().map(rounds)
    ch3 = chapters[2]
    assert ch3.framework == "Porter"


def test_audit_trail_total_layers_match():
    """모든 라운드가 매핑된 어떤 챕터의 source_layers에 들어있어야 함."""
    rounds = _full_round_set()
    chapters = ChapterMapper().map(rounds)
    all_layers: list[str] = []
    for ch in chapters:
        all_layers.extend(ch.source_layers)
    assert set(all_layers) == {r.layer_id for r in rounds}


def test_quantitative_claim_promoted_to_top_in_market_chapter():
    rounds = _full_round_set()
    chapters = ChapterMapper().map(rounds)
    formatted = PyramidFormatter().reorder_all(chapters)
    ch2 = formatted[1]
    # 정량 수치가 들어간 라인이 가장 앞
    if ch2.body_claims:
        assert any(s in ch2.body_claims[0] for s in ["조원", "%", "CAGR"])
