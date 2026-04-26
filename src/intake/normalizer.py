"""Lightweight normalization for raw idea dumps."""
from __future__ import annotations

from .idea_dump import IdeaDump


def normalize_idea_text(text: str) -> str:
    """Trim surrounding whitespace while preserving user wording."""
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def capture_idea(raw_text: str, *, source: str = "user") -> IdeaDump:
    idea = IdeaDump(raw_text=normalize_idea_text(raw_text), source=source)
    idea.validate()
    return idea
