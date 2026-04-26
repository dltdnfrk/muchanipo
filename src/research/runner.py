"""AutoResearch runner implementations."""
from __future__ import annotations

from src.evidence.artifact import EvidenceRef, Finding
from src.evidence.provenance import Provenance

from .planner import ResearchPlan
from .synthesis import finding_from_query


class MockResearchRunner:
    """API-key-free runner used by tests and early pipeline wiring."""

    def run(self, plan: ResearchPlan) -> list[Finding]:
        findings: list[Finding] = []
        for idx, query in enumerate(plan.queries or ["research question"], start=1):
            evidence = EvidenceRef(
                id=f"mock-evidence-{idx}",
                source_url=None,
                source_title="Mock research evidence",
                quote=query,
                source_grade="B",
                provenance=Provenance(kind="mock", metadata={"brief_id": plan.brief_id}).as_dict(),
            )
            findings.append(finding_from_query(query, evidence))
        return findings
