"""InterviewRubric (Phase 0b v2) 테스트 — entropy-greedy + coverage gate."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path("src/intent")))
from interview_rubric import (  # type: ignore
    CoverageStatus,
    InterviewRubric,
    RubricItem,
)


def test_rubric_default_six_items():
    r = InterviewRubric(topic="MIRIVA 가격 책정")
    assert len(r.items) == 6
    ids = [i.dimension_id for i in r.items]
    assert "Q1_research_question" in ids
    assert "Q6_quality" in ids


def test_coverage_rate_zero_initial():
    r = InterviewRubric(topic="x")
    assert r.coverage_rate() == 0.0
    assert r.is_complete(threshold=0.75) is False


def test_next_uncovered_picks_max_entropy():
    r = InterviewRubric(topic="x")
    # 첫 호출 — 모든 차원 entropy=1.0 → 첫 항목(Q1) 우선
    first = r.next_uncovered()
    assert first is not None
    assert first.dimension_id == "Q1_research_question"

    # Q1 답변 후 — entropy 0으로 떨어지면 Q2가 다음
    r.update("Q1_research_question", "한국 사과 농가 진단키트 가격", quality=0.9)
    second = r.next_uncovered()
    assert second is not None
    assert second.dimension_id == "Q2_purpose"


def test_next_uncovered_skips_partially_answered_with_low_entropy():
    """quality 0.5(insufficient)인 차원은 entropy 0.5 — 미답변 1.0보다 낮음."""
    r = InterviewRubric(topic="x")
    # Q1을 부분 답변 (insufficient)
    r.update("Q1_research_question", "?", quality=0.5)
    # 미답변 Q2~Q6 (entropy=1.0)이 우선이어야
    nxt = r.next_uncovered()
    assert nxt is not None
    assert nxt.dimension_id != "Q1_research_question"


def test_is_complete_threshold_075():
    r = InterviewRubric(topic="x")
    # 5/6 = 0.833 ≥ 0.75 → complete
    for did in ["Q1_research_question", "Q2_purpose", "Q3_context",
                "Q4_known", "Q5_deliverable"]:
        r.update(did, "답변", quality=0.9)
    assert r.coverage_rate() >= 0.75
    assert r.is_complete(threshold=0.75) is True

    # 4/6 = 0.666 < 0.75 → not complete
    r2 = InterviewRubric(topic="y")
    for did in ["Q1_research_question", "Q2_purpose", "Q3_context", "Q4_known"]:
        r2.update(did, "답변", quality=0.9)
    assert r2.is_complete(threshold=0.75) is False


def test_mark_answered_updates_status():
    item = RubricItem(
        dimension_id="Q1_research_question",
        label="research_question",
        research_question="?",
    )
    assert item.coverage_status == CoverageStatus.NOT_ASKED
    item.mark_answered("좋은 답변", quality=0.9)
    assert item.coverage_status == CoverageStatus.COVERED
    assert item.entropy_estimate < 0.2

    item2 = RubricItem(
        dimension_id="Q2", label="x", research_question="?"
    )
    item2.mark_answered("애매한 답변", quality=0.4)
    assert item2.coverage_status == CoverageStatus.ASKED_INSUFFICIENT


def test_uncovered_dimension_ids():
    r = InterviewRubric(topic="x")
    r.update("Q1_research_question", "답변", quality=0.9)
    uncov = r.uncovered_dimension_ids()
    assert "Q1_research_question" not in uncov
    assert len(uncov) == 5


def test_unknown_dimension_raises():
    r = InterviewRubric(topic="x")
    try:
        r.update("Q99_bogus", "x", 0.5)
        assert False, "expected KeyError"
    except KeyError:
        pass
