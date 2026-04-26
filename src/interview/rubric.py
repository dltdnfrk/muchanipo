"""Coverage rubric for PRD-style research interviews."""
from __future__ import annotations

REQUIRED_DIMENSIONS = (
    "research_question",
    "purpose",
    "context",
    "deliverable_type",
    "quality_bar",
)


def coverage_score(answers: dict[str, str]) -> float:
    if not REQUIRED_DIMENSIONS:
        return 1.0
    covered = sum(1 for key in REQUIRED_DIMENSIONS if answers.get(key, "").strip())
    return covered / len(REQUIRED_DIMENSIONS)


def missing_dimensions(answers: dict[str, str]) -> list[str]:
    return [key for key in REQUIRED_DIMENSIONS if not answers.get(key, "").strip()]
