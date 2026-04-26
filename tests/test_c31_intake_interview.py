import pytest

from src.intake.idea_dump import IdeaDump
from src.interview.session import InterviewSession


def test_idea_dump_rejects_empty_text():
    with pytest.raises(ValueError):
        IdeaDump(raw_text="   ").validate()


def test_idea_dump_uses_independent_lists():
    first = IdeaDump(raw_text="a")
    second = IdeaDump(raw_text="b")
    first.tags.append("x")
    assert second.tags == []


def test_interview_session_builds_ready_research_brief():
    session = InterviewSession.from_idea(IdeaDump(raw_text="AI memory agent idea"))
    session.answer("research_question", "What should we build?")
    session.answer("purpose", "Decide next sprint")
    session.answer("context", "muchanipo")
    session.answer("deliverable_type", "architecture brief")
    session.answer("quality_bar", "evidence-backed and actionable")
    brief = session.to_brief()
    assert brief.is_ready
    assert brief.coverage_score >= 0.75
    assert brief.raw_idea == "AI memory agent idea"
