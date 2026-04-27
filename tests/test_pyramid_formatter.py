"""PyramidFormatter 단위 테스트."""

from __future__ import annotations

from src.report.chapter_mapper import Chapter
from src.report.pyramid_formatter import PyramidFormatter, _importance_score


def _ch(no, body, scr=None):
    return Chapter(
        chapter_no=no,
        title=f"Test Ch{no}",
        lead_claim="lead claim",
        body_claims=body,
        source_layers=["L1_test"],
        scr=scr,
    )


# ---- standard chapter (2~6) ---------------------------------------------


def test_quantitative_claim_ranked_higher():
    body = ["short note", "TAM is 10조원 according to KIET 2026"]
    out = PyramidFormatter().reorder(_ch(2, body))
    assert out.body_claims[0] == "TAM is 10조원 according to KIET 2026"


def test_dedupe_against_lead_claim():
    body = ["lead claim", "lead claim", "real body"]
    out = PyramidFormatter().reorder(_ch(2, body))
    assert "lead claim" not in out.body_claims  # lead와 중복 제거
    assert "real body" in out.body_claims


def test_dedupe_within_body():
    body = ["claim A", "claim A", "claim B"]
    out = PyramidFormatter().reorder(_ch(2, body))
    assert out.body_claims.count("claim A") == 1


def test_empty_body_returns_chapter_unchanged():
    ch = _ch(3, [])
    out = PyramidFormatter().reorder(ch)
    assert out is ch  # 동일 객체


def test_strong_verb_increases_score():
    body = ["random comment text", "결론: TAM is significant"]
    out = PyramidFormatter().reorder(_ch(4, body))
    assert out.body_claims[0].startswith("결론:")


# ---- executive (chapter 1) ----------------------------------------------


def test_executive_renders_scr_block_in_order():
    scr = {"situation": "S text", "complication": "C text", "resolution": "R text"}
    body = ["[Situation] S text", "[Complication] C text", "[Resolution] R text", "extra detail"]
    out = PyramidFormatter().reorder(_ch(1, body, scr=scr))
    # 첫 3줄은 SCR 순서
    assert out.body_claims[0] == "[Situation] S text"
    assert out.body_claims[1] == "[Complication] C text"
    assert out.body_claims[2] == "[Resolution] R text"
    # 나머지는 부록
    assert "extra detail" in out.body_claims


def test_executive_skips_missing_scr_blocks():
    scr = {"situation": "", "complication": "C", "resolution": "R"}
    body = ["[Complication] C", "[Resolution] R"]
    out = PyramidFormatter().reorder(_ch(1, body, scr=scr))
    assert out.body_claims[0] == "[Complication] C"
    assert out.body_claims[1] == "[Resolution] R"
    # Situation 빈 문자열이라 첫 블록 없음
    assert all(not c.startswith("[Situation]") for c in out.body_claims)


def test_executive_without_scr_falls_back_to_standard_reorder():
    """scr=None인 챕터1은 일반 정렬."""
    out = PyramidFormatter().reorder(_ch(1, ["claim 1"], scr=None))
    assert out.body_claims == ["claim 1"]


# ---- batch --------------------------------------------------------------


def test_reorder_all_processes_each_chapter():
    chapters = [_ch(1, [], scr={"situation": "", "complication": "", "resolution": ""}),
                _ch(2, ["body x"]),
                _ch(3, ["body y"])]
    out = PyramidFormatter().reorder_all(chapters)
    assert len(out) == 3
    assert out[1].body_claims == ["body x"]


# ---- score helper -------------------------------------------------------


def test_importance_score_rewards_numbers_and_sources():
    high = _importance_score("매출 100억원 출처 KDI 2026")
    low = _importance_score("그냥 짧은 메모")
    assert high > low


def test_importance_score_penalizes_too_short_strings():
    short = _importance_score("hi")
    longer = _importance_score("이 문장은 충분히 깁니다 그래서 정상")
    assert longer > short
