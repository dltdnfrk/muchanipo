import pytest

from src.intake.idea_dump import IdeaDump
from src.interview.brief import ResearchBrief
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
    assert brief.planning_prd["overview"]["one_line"] == "What should we build?"
    assert brief.feature_hierarchy[0]["features"][0]["name"] == "architecture brief"
    assert brief.user_flow["nodes"]


def test_research_brief_round_trips_product_planning_projection():
    session = InterviewSession.from_idea(IdeaDump(raw_text="AI memory agent idea"))
    session.answer("research_question", "What should we build?")
    session.answer("purpose", "Decide next sprint")
    session.answer("context", "muchanipo web")
    session.answer("deliverable_type", "architecture brief")
    session.answer("quality_bar", "evidence-backed and actionable")

    brief = session.to_brief()
    restored = type(brief).from_dict(brief.to_dict())

    assert restored.planning_prd == brief.planning_prd
    assert restored.feature_hierarchy == brief.feature_hierarchy
    assert restored.user_flow == brief.user_flow
    assert restored.planning_review_policy == brief.planning_review_policy


def test_research_brief_from_dict_tolerates_null_planning_fields():
    restored = ResearchBrief.from_dict(
        {
            "raw_idea": "x",
            "research_question": "q",
            "purpose": "p",
            "known_facts": None,
            "constraints": None,
            "success_criteria": None,
            "planning_prd": None,
            "feature_hierarchy": None,
            "user_flow": None,
            "planning_review_policy": None,
        }
    )

    assert restored.known_facts == []
    assert restored.constraints == []
    assert restored.success_criteria == []
    assert restored.planning_prd == {}
    assert restored.feature_hierarchy == []
    assert restored.user_flow == {}
    assert restored.planning_review_policy == {}
