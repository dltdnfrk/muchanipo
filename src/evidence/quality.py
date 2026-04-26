"""Evidence quality grades."""
from __future__ import annotations

VALID_SOURCE_GRADES = {"A", "B", "C", "D"}


def validate_source_grade(grade: str) -> None:
    if grade not in VALID_SOURCE_GRADES:
        raise ValueError(f"invalid source_grade: {grade}")
