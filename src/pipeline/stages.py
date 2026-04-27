"""Canonical stages for the Idea-to-Council lifecycle."""
from __future__ import annotations

from enum import Enum


class Stage(str, Enum):
    IDEA_DUMP = "idea_dump"
    INTERVIEW = "interview"
    TARGETING = "targeting"
    RESEARCH = "research"
    EVIDENCE = "evidence"
    COUNCIL = "council"
    REPORT = "report"
    VAULT = "vault"
    AGENTS = "agents"
    DONE = "done"
