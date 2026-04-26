"""Coverage rubric for PRD-style research interviews.

C32 wire: re-exports the canonical Phase 0b v2 rubric defined in
src.intent.interview_rubric so we keep a single InterviewRubric definition.
The legacy 5-key dict-based helpers (REQUIRED_DIMENSIONS / coverage_score /
missing_dimensions) are preserved for back-compat with C31 callers.
"""
from __future__ import annotations

from typing import Mapping

from src.intent.interview_rubric import (
    CoverageStatus,
    InterviewRubric,
    RubricItem,
)

__all__ = [
    "CoverageStatus",
    "InterviewRubric",
    "RubricItem",
    "REQUIRED_DIMENSIONS",
    "coverage_score",
    "missing_dimensions",
    "rubric_from_answers",
]


# Legacy 5-key contract (pre-C32). Maps onto rubric labels Q1..Q5; Q6 is the
# extra quality axis only the entropy-greedy rubric tracks.
REQUIRED_DIMENSIONS = (
    "research_question",
    "purpose",
    "context",
    "deliverable_type",
    "quality_bar",
)

# label → dimension_id (Q* in interview_rubric)
_LABEL_TO_DIM_ID = {
    "research_question": "Q1_research_question",
    "purpose": "Q2_purpose",
    "context": "Q3_context",
    "deliverable_type": "Q5_deliverable",
    "quality_bar": "Q6_quality",
}


def coverage_score(answers: Mapping[str, str]) -> float:
    """Backward-compatible coverage over the legacy 5 dimensions."""
    if not REQUIRED_DIMENSIONS:
        return 1.0
    covered = sum(
        1 for key in REQUIRED_DIMENSIONS if str(answers.get(key, "")).strip()
    )
    return covered / len(REQUIRED_DIMENSIONS)


def missing_dimensions(answers: Mapping[str, str]) -> list[str]:
    return [key for key in REQUIRED_DIMENSIONS if not str(answers.get(key, "")).strip()]


def rubric_from_answers(topic: str, answers: Mapping[str, str]) -> InterviewRubric:
    """Build an InterviewRubric primed with the supplied legacy-shape answers.

    Each present answer is recorded with quality=0.8 so it counts as COVERED
    under the entropy-greedy gate (>=0.7 threshold).
    """
    rubric = InterviewRubric(topic=topic)
    for label, dim_id in _LABEL_TO_DIM_ID.items():
        text = str(answers.get(label, "")).strip()
        if text:
            rubric.update(dim_id, text, quality=0.8)
    return rubric
