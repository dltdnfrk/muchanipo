"""Interview trace provenance tests."""
from __future__ import annotations

from src.intent.interview_prompts import merge_answers_to_text
from src.intent.office_hours import OfficeHours
from src.interview.session import InterviewSession
from src.intake.idea_dump import IdeaDump
from src.pipeline.idea_to_council import IdeaToCouncilPipeline, _extract_embedded_interview_answers


def test_merged_answers_format_is_parseable() -> None:
    merged = merge_answers_to_text(
        "strawberry market",
        [
            {"id": "Q1_research_question", "answer": "Korean strawberry market size"},
            {"id": "Q2_purpose", "answer": "investment review"},
            {"id": "Q3_context", "answer": "Korean AgTech"},
        ],
    )

    extracted = _extract_embedded_interview_answers(merged)

    assert extracted["research_question"] == "Korean strawberry market size"
    assert extracted["purpose"] == "investment review"
    assert extracted["context"] == "Korean AgTech"


def test_partial_user_answers_are_marked_mixed_not_fully_synthetic() -> None:
    topic = merge_answers_to_text(
        "strawberry market",
        [
            {"id": "Q1_research_question", "answer": "Korean strawberry market size"},
            {"id": "Q2_purpose", "answer": "investment review"},
            {"id": "Q3_context", "answer": "Korean AgTech"},
        ],
    )
    idea = IdeaDump(raw_text=topic)
    interview = InterviewSession.from_idea(idea)
    design_doc = OfficeHours().reframe(idea.raw_text)

    brief = IdeaToCouncilPipeline(require_live=False, depth="shallow")._brief_from_interview(
        interview,
        idea.raw_text,
        design_doc,
    )

    assert brief.research_question == "Korean strawberry market size"
    assert getattr(brief, "interview_trace_source") == "mixed_user_office_hours"
    assert getattr(brief, "synthetic_interview_trace") is False
    assert getattr(brief, "mixed_interview_trace") is True
    assert getattr(brief, "interview_user_answer_count") == 3
    assert getattr(brief, "interview_office_hours_fill_count") > 0
