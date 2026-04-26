"""ResearchBrief contract produced by the PRD-style interview."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ResearchBrief:
    raw_idea: str
    research_question: str
    purpose: str
    context: str = ""
    known_facts: list[str] = field(default_factory=list)
    deliverable_type: str = "report"
    quality_bar: str = "evidence-backed"
    constraints: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    coverage_score: float = 0.0

    @property
    def id(self) -> str:
        seed = self.research_question or self.raw_idea or "brief"
        return "brief-" + str(abs(hash(seed)) % 10_000_000)

    @property
    def is_ready(self) -> bool:
        return bool(
            self.research_question.strip()
            and self.purpose.strip()
            and self.coverage_score >= 0.75
        )
