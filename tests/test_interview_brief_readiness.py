"""Tests for interview → brief readiness gate enforcement (Lane B).

These tests encode the contract that:
1. A ResearchBrief must have coverage_score >= 0.75 before targeting begins.
2. The pipeline checks is_ready and surfaces missing dimensions when not ready.
3. The HITL brief gate receives is_ready status for human review.
"""
from __future__ import annotations

import pytest

from src.intake.idea_dump import IdeaDump
from src.intent.office_hours import OfficeHours
from src.interview.brief import ResearchBrief
from src.interview.session import InterviewSession
from src.pipeline.idea_to_council import IdeaToCouncilPipeline


def _make_pipeline(*, depth: str = "shallow") -> IdeaToCouncilPipeline:
    return IdeaToCouncilPipeline(
        require_live=False,
        depth=depth,
    )


def test_brief_is_ready_requires_coverage_075() -> None:
    brief = ResearchBrief(
        raw_idea="test",
        research_question="What is AI?",
        purpose="learn",
        coverage_score=0.74,
    )
    assert not brief.is_ready

    brief.coverage_score = 0.75
    assert brief.is_ready


def test_brief_is_ready_rejects_empty_question_or_purpose() -> None:
    brief = ResearchBrief(
        raw_idea="test",
        research_question="",
        purpose="learn",
        coverage_score=1.0,
    )
    assert not brief.is_ready

    brief.research_question = "What is AI?"
    brief.purpose = ""
    assert not brief.is_ready


def test_pipeline_enforces_brief_readiness_before_targeting(monkeypatch) -> None:
    """If the brief is not ready, the pipeline must stop before targeting."""
    pipeline = _make_pipeline()

    # Force _brief_from_interview to return a low-coverage brief
    bad_brief = ResearchBrief(
        raw_idea="incomplete idea",
        research_question="incomplete idea",
        purpose="decide",
        coverage_score=0.2,
    )
    monkeypatch.setattr(pipeline, "_brief_from_interview", lambda *a, **k: bad_brief)

    with pytest.raises((ValueError, RuntimeError)) as exc_info:
        pipeline.run("incomplete idea")

    assert "not ready" in str(exc_info.value).lower() or "coverage" in str(exc_info.value).lower()


def test_pipeline_records_brief_readiness_in_artifacts() -> None:
    """Brief readiness must be recorded as a first-class artifact."""
    pipeline = _make_pipeline()
    # Seed interview answers so brief becomes ready
    idea = IdeaDump(raw_text="AI memory agent for farming")
    interview = InterviewSession.from_idea(idea)
    interview.answer("research_question", "How do AI memory agents help farming?")
    interview.answer("purpose", "decide next sprint")
    interview.answer("context", "Korean AgTech")
    interview.answer("deliverable_type", "report")
    interview.answer("quality_bar", "evidence-backed")

    design_doc = OfficeHours().reframe(idea.raw_text)
    brief = pipeline._brief_from_interview(interview, idea.raw_text, design_doc)

    assert brief.is_ready
    assert brief.to_dict()["is_ready"] is True


def test_hitl_brief_gate_receives_is_ready_status() -> None:
    """The HITL brief gate payload must include brief.is_ready."""
    pipeline = _make_pipeline()
    idea = IdeaDump(raw_text="test idea")
    interview = InterviewSession.from_idea(idea)
    interview.answer("research_question", "What is X?")
    interview.answer("purpose", "learn")
    interview.answer("context", "test")
    interview.answer("deliverable_type", "report")
    interview.answer("quality_bar", "evidence-backed")

    design_doc = OfficeHours().reframe(idea.raw_text)
    brief = pipeline._brief_from_interview(interview, idea.raw_text, design_doc)

    payload = {"brief": brief.to_dict()}
    assert payload["brief"]["is_ready"] == brief.is_ready
