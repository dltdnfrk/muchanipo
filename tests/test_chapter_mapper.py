"""ChapterMapper 단위 테스트 — PRD-v2 §7.4 Dual Structure 매핑."""

from __future__ import annotations

import pytest

from src.report.chapter_mapper import (
    CHAPTER_TITLES,
    Chapter,
    ChapterMapper,
    RoundDigest,
)


def _digest(layer_id: str, key_claim: str, body=(), confidence=0.7) -> RoundDigest:
    return RoundDigest(
        layer_id=layer_id,
        chapter_title="(test)",
        key_claim=key_claim,
        body_claims=list(body),
        confidence=confidence,
    )


# ---- mapping rules ------------------------------------------------------


def test_map_l10_to_chapter_1_executive_summary():
    rounds = [
        _digest("L10_executive_synthesis", "Resolution claim", body=["S", "C", "R"]),
    ]
    chapters = ChapterMapper().map(rounds)
    assert chapters[0].chapter_no == 1
    assert chapters[0].title == "Executive Summary"
    assert "L10_executive_synthesis" in chapters[0].source_layers


def test_map_l1_and_l3_to_chapter_2_market():
    rounds = [
        _digest("L1_market_sizing", "TAM is 10B", confidence=0.9),
        _digest("L3_jtbd", "JTBD is X", confidence=0.7),
    ]
    chapters = ChapterMapper().map(rounds)
    ch2 = chapters[1]
    assert ch2.chapter_no == 2
    assert ch2.title == "시장 기회"
    assert set(ch2.source_layers) == {"L1_market_sizing", "L3_jtbd"}


def test_map_l5_and_l9_to_chapter_5_risks():
    rounds = [
        _digest("L5_risk", "supply chain risk"),
        _digest("L9_dissent", "dissent: legal exposure"),
    ]
    chapters = ChapterMapper().map(rounds)
    ch5 = chapters[4]
    assert ch5.chapter_no == 5
    assert ch5.title == "리스크 및 대응"
    assert len(ch5.source_layers) == 2


def test_map_l6_l7_l8_to_chapter_6_roadmap():
    rounds = [
        _digest("L6_roadmap", "90-day plan"),
        _digest("L7_governance", "decision body X"),
        _digest("L8_kpi", "north star = MAU"),
    ]
    chapters = ChapterMapper().map(rounds)
    ch6 = chapters[5]
    assert ch6.chapter_no == 6
    assert len(ch6.source_layers) == 3


def test_unknown_layer_skipped():
    rounds = [_digest("L99_unknown", "should be skipped")]
    chapters = ChapterMapper().map(rounds)
    # 모든 챕터가 빈 상태 (출처 라운드 없음)
    for ch in chapters:
        assert ch.source_layers == []


# ---- pyramid principle: lead_claim -------------------------------------


def test_lead_claim_uses_highest_confidence_round():
    rounds = [
        _digest("L1_market_sizing", "low conf claim", confidence=0.3),
        _digest("L1_market_sizing", "high conf claim", confidence=0.95),
    ]
    chapters = ChapterMapper().map(rounds)
    ch2 = chapters[1]
    assert ch2.lead_claim == "high conf claim"


def test_executive_summary_lead_is_resolution():
    rounds = [
        _digest(
            "L10_executive_synthesis",
            "key claim text",
            body=["situation here", "complication here", "resolution here"],
            confidence=0.8,
        ),
    ]
    chapters = ChapterMapper().map(rounds)
    ch1 = chapters[0]
    assert ch1.lead_claim == "resolution here"
    assert ch1.scr is not None
    assert ch1.scr["situation"] == "situation here"
    assert ch1.scr["complication"] == "complication here"
    assert ch1.scr["resolution"] == "resolution here"


def test_executive_summary_falls_back_to_key_claim_when_body_short():
    rounds = [
        _digest("L10_executive_synthesis", "the only claim", body=["only situation"]),
    ]
    chapters = ChapterMapper().map(rounds)
    ch1 = chapters[0]
    # body_claims < 3 → resolution은 빈 문자열, key_claim으로 폴백
    assert ch1.scr["resolution"] == "the only claim"
    assert ch1.lead_claim == "the only claim"


# ---- chapter shape ------------------------------------------------------


def test_all_six_chapters_always_present():
    chapters = ChapterMapper().map([])
    assert len(chapters) == 6
    assert [c.chapter_no for c in chapters] == [1, 2, 3, 4, 5, 6]
    assert [c.title for c in chapters] == [CHAPTER_TITLES[i] for i in range(1, 7)]


def test_empty_chapter_indicates_missing_research():
    chapters = ChapterMapper().map([])
    for ch in chapters:
        assert "추가 리서치 필요" in ch.lead_claim or "L10 라운드 없음" in ch.lead_claim


def test_chapter_confidence_is_average():
    rounds = [
        _digest("L5_risk", "claim a", confidence=0.4),
        _digest("L9_dissent", "claim b", confidence=0.8),
    ]
    chapters = ChapterMapper().map(rounds)
    ch5 = chapters[4]
    assert ch5.confidence == pytest.approx(0.6)


def test_chapter_picks_first_framework_available():
    rounds = [
        RoundDigest(
            layer_id="L2_competition",
            chapter_title="경쟁",
            key_claim="forces strong",
            framework="Porter",
            confidence=0.8,
        ),
    ]
    chapters = ChapterMapper().map(rounds)
    ch3 = chapters[2]
    assert ch3.framework == "Porter"


# ---- audit trail --------------------------------------------------------


def test_source_layers_preserves_audit_trail():
    rounds = [
        _digest("L6_roadmap", "plan", confidence=0.7),
        _digest("L7_governance", "gov", confidence=0.6),
    ]
    chapters = ChapterMapper().map(rounds)
    ch6 = chapters[5]
    assert "L6_roadmap" in ch6.source_layers
    assert "L7_governance" in ch6.source_layers


def test_custom_layer_to_chapter_override():
    """매핑 규칙 변경 가능 (다른 보고서 포맷용)."""
    custom = {"L1": 5, "L2": 5}  # 모두 chapter 5로
    mapper = ChapterMapper(layer_to_chapter=custom)
    rounds = [_digest("L1_market_sizing", "claim 1"), _digest("L2_competition", "claim 2")]
    chapters = mapper.map(rounds)
    ch5 = chapters[4]
    assert len(ch5.source_layers) == 2
