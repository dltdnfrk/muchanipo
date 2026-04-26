import pytest

from src.interview.brief import ResearchBrief
from src.research.planner import ResearchPlanner
from src.research.runner import MockResearchRunner
from src.evidence.store import EvidenceStore
from src.evidence.artifact import EvidenceRef


def test_research_planner_creates_query_from_brief():
    brief = ResearchBrief(raw_idea="x", research_question="How to design agent memory?", purpose="plan")
    plan = ResearchPlanner().plan(brief)
    assert plan.brief_id
    assert "How to design agent memory?" in plan.queries


def test_mock_research_runner_returns_finding_with_evidence():
    brief = ResearchBrief(raw_idea="x", research_question="How to design agent memory?", purpose="plan")
    plan = ResearchPlanner().plan(brief)
    findings = MockResearchRunner().run(plan)
    assert findings[0].support[0].source_grade == "B"
    assert findings[0].confidence > 0


def test_evidence_store_validates_source_grade():
    store = EvidenceStore()
    ref = EvidenceRef(id="e1", source_url=None, source_title="Mock", quote="q", source_grade="A", provenance={"kind": "mock"})
    store.add(ref)
    assert store.get("e1") == ref
    with pytest.raises(ValueError):
        EvidenceRef(id="bad", source_url=None, source_title=None, quote=None, source_grade="Z", provenance={}).validate()
