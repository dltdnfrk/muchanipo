"""ResearchBrief to ResearchPlan conversion."""
from __future__ import annotations

from dataclasses import dataclass, field

from src.interview.brief import ResearchBrief


@dataclass
class ResearchPlan:
    brief_id: str
    queries: list[str]
    evidence_targets: list[str] = field(default_factory=list)
    expected_deliverables: list[str] = field(default_factory=list)
    stop_conditions: list[str] = field(default_factory=list)
    risk_notes: list[str] = field(default_factory=list)


class ResearchPlanner:
    def plan(self, brief: ResearchBrief) -> ResearchPlan:
        query = brief.research_question.strip() or brief.raw_idea.strip()
        return ResearchPlan(
            brief_id=brief.id,
            queries=[query],
            evidence_targets=[brief.context] if brief.context else [],
            expected_deliverables=[brief.deliverable_type],
            stop_conditions=["enough evidence for first report"],
        )
