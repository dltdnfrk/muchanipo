"""Research report schema for Idea-to-Council."""
from __future__ import annotations

from dataclasses import dataclass, field

from src.evidence.artifact import EvidenceRef, Finding


@dataclass
class ResearchReport:
    brief_id: str
    title: str
    executive_summary: str
    findings: list[Finding] = field(default_factory=list)
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    confidence: float = 0.0
    limitations: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.brief_id
