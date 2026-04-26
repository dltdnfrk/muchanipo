"""Canonical stages for the Idea-to-Council lifecycle."""
from __future__ import annotations

from enum import Enum


class Stage(str, Enum):
    IDEA_DUMP = "idea_dump"
    INTERVIEW = "interview"
    RESEARCH = "research"
    REPORT = "report"
    AGENTS = "agents"
    COUNCIL = "council"
    DONE = "done"
