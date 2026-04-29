import pytest

from src.interview.brief import ResearchBrief
from src.research.planner import ResearchPlanner
from src.research.runner import MockResearchRunner
from src.research.queries import expand_query
from src.evidence.store import EvidenceStore
from src.evidence.artifact import EvidenceRef


def test_research_planner_creates_query_from_brief():
    brief = ResearchBrief(raw_idea="x", research_question="How to design agent memory?", purpose="plan")
    plan = ResearchPlanner().plan(brief)
    assert plan.brief_id
    assert "How to design agent memory?" in plan.queries
    assert any("counter evidence" in query for query in plan.queries)
    assert "do not treat LLM output as evidence" in plan.risk_notes
    assert any("provenance" in rule for rule in plan.collection_rules)


def test_expand_query_adds_evidence_intents_without_duplicates():
    queries = expand_query(
        "Korean agtech diagnostic kit pricing",
        context="strawberry farms",
        quality_bar="A/B sources",
    )
    assert queries[0] == "Korean agtech diagnostic kit pricing"
    assert any("official statistics" in query for query in queries)
    assert any("counter evidence" in query for query in queries)
    assert len(queries) == len(set(queries))


def test_mock_research_runner_returns_finding_with_evidence():
    brief = ResearchBrief(raw_idea="x", research_question="How to design agent memory?", purpose="plan")
    plan = ResearchPlanner().plan(brief)
    findings = MockResearchRunner().run(plan)
    assert findings[0].support[0].source_grade == "B"
    assert findings[0].confidence > 0


def test_evidence_store_validates_source_grade():
    store = EvidenceStore()
    ref = EvidenceRef(
        id="e1",
        source_url=None,
        source_title="Mock",
        quote="q",
        source_grade="A",
        provenance={"kind": "mock", "source_text": "q"},
    )
    store.add(ref)
    assert store.get("e1") == ref
    assert store.summary()["grades"] == {"A": 1}
    assert store.summary()["trusted"] == 1
    with pytest.raises(ValueError):
        EvidenceRef(id="bad", source_url=None, source_title=None, quote=None, source_grade="Z", provenance={}).validate()
