from __future__ import annotations

import io
import json

from src.evidence.artifact import EvidenceRef, Finding
from src.evidence.provenance import Provenance
from src.muchanipo.server import serve_full
from src.research.karpathy_autoresearch import build_research_quality_audit
from src.research.planner import ResearchPlan


def _ref(
    ref_id: str,
    *,
    kind: str,
    title: str,
    quote: str,
    url: str | None = None,
    grade: str = "A",
    query: str = "low cost strawberry molecular diagnostic kit market pricing adoption",
) -> EvidenceRef:
    return EvidenceRef(
        id=ref_id,
        source_url=url or f"https://example.test/{ref_id}",
        source_title=title,
        quote=quote,
        source_grade=grade,
        provenance=Provenance(
            kind=kind,
            metadata={"query": query, "source": url or f"https://example.test/{ref_id}"},
        ).as_dict(),
    )


def test_research_quality_audit_reports_facet_coverage_and_gaps() -> None:
    plan = ResearchPlan(
        brief_id="brief-market-diagnostics",
        queries=["low cost strawberry molecular diagnostic kit market pricing adoption"],
    )
    findings = [
        Finding(
            claim="PCR and LAMP can support field molecular diagnostic kit feasibility.",
            support=[
                _ref(
                    "paper-1",
                    kind="academic",
                    title="Rapid molecular diagnostics for plant pathogens",
                    quote="Plant pathogen PCR and LAMP diagnostics are applicable to strawberry disease detection.",
                    url="https://doi.org/10.1000/plant-diagnostics",
                ),
                _ref(
                    "paper-2",
                    kind="doi",
                    title="Field validation of strawberry pathogen LAMP assay",
                    quote="Field validation reported sensitivity and specificity for strawberry pathogen detection.",
                    url="https://doi.org/10.1000/strawberry-lamp",
                ),
            ],
        )
    ]

    audit = build_research_quality_audit(findings, plan)
    payload = audit.to_dict()

    assert payload["facets"]["scientific"]["accepted_count"] >= 2
    assert payload["facets"]["market"]["accepted_count"] == 0
    assert payload["gaps"]
    assert any(gap["facet_id"] == "market" for gap in payload["gaps"])
    assert payload["source_evaluations"]
    assert all("accepted" in item and "facet_ids" in item and "reason" in item for item in payload["source_evaluations"])


def test_regional_consumer_statistics_source_satisfies_market_and_regional_adoption() -> None:
    plan = ResearchPlan(
        brief_id="brief-regional-market",
        queries=[
            "Korea low cost diagnostic kit market adoption pricing",
            "Korea market consumer trend purchase price statistics",
        ],
        topic_anchor="Korea low cost diagnostic kit market adoption pricing",
    )
    findings = [
        Finding(
            claim="Korea government public data provides consumer trends and monthly purchase changes for diagnostic kits.",
            support=[
                _ref(
                    "gov-consumer-stat",
                    kind="government",
                    title="Korea Diagnostic Kit Market Consumer Trends Monthly Purchase Change",
                    quote="Korea consumer trend purchase price survey government public data statistics for diagnostic kits",
                    url="https://www.data.go.kr/data/15156401/fileData.do",
                    query="Korea diagnostic kit market consumer trend purchase price statistics",
                )
            ],
        )
    ]

    payload = build_research_quality_audit(findings, plan).to_dict()

    assert payload["source_evaluations"][0]["accepted"] is True
    assert "market" in payload["source_evaluations"][0]["facet_ids"]
    assert "regional_adoption" in payload["source_evaluations"][0]["facet_ids"]


def test_diagnostic_kit_plan_requires_regional_adoption_facet() -> None:
    plan = ResearchPlan(
        brief_id="brief-diagnostic-kit",
        queries=[
            "low cost molecular diagnostic kit market adoption pricing",
            "molecular diagnostic pathogen detection kit low cost field validation market adoption pricing Korea",
        ],
    )

    audit = build_research_quality_audit([], plan)
    facet_ids = set(audit.to_dict()["facets"].keys())

    assert {"scientific", "field_validation", "market", "regional_adoption"}.issubset(facet_ids)


def test_live_diagnostic_plan_spends_one_limited_slot_on_scientific_followup() -> None:
    """Verification that local market/regional coverage reserves one translated
    bridge query for paper/DOI/assay/review evidence so academic search has
    more than the broad base query to satisfy the scientific facet."""

    from src.interview.brief import ResearchBrief
    from src.research.planner import ResearchPlanner

    topic = "low cost molecular diagnostic kit market adoption field validation source-backed Deep Research council persona verification"
    brief = ResearchBrief(
        raw_idea=topic,
        research_question=topic,
        purpose="research_report",
        original_topic=topic,
    )

    plan = ResearchPlanner().plan(brief, max_queries=9)
    joined = "\n".join(plan.queries).casefold()

    assert any("peer reviewed" in query.casefold() and "assay" in query.casefold() for query in plan.queries)
    assert "government statistics willingness to pay adoption market adoption" in joined or "pricing" in joined
    assert "consumer trend purchase" in joined or "adoption" in joined
    assert "government statistics willingness to pay adoption market adoption" in joined


def test_serve_full_streams_source_evaluation_and_knowledge_gap_events(tmp_path, monkeypatch) -> None:
    import src.pipeline.runner as runner_mod

    def fake_run_pipeline(topic, **kwargs):
        progress_callback = kwargs["progress_callback"]
        progress_callback(
            {
                "event": "research_progress",
                "stage": "research",
                "status": "source_evaluated",
                "source_title": "Rapid molecular diagnostics for plant pathogens",
                "source_url": "https://doi.org/10.1000/plant-diagnostics",
                "source_grade": "A",
                "source_kind": "paper",
                "accepted": True,
                "facet_ids": ["scientific"],
                "relevance_score": 0.83,
                "reason": "accepted for scientific facet",
            }
        )
        progress_callback(
            {
                "event": "research_progress",
                "stage": "research",
                "status": "knowledge_gap",
                "facet_id": "market",
                "message": "Need pricing/adoption evidence",
                "required_source_kinds": ["statistics", "industry_report", "government", "pricing_page"],
                "accepted_count": 0,
                "min_accepted_sources": 3,
            }
        )
        return {
            "rounds": [],
            "executed_council_round_count": 0,
            "council_turn_transcript": [],
            "report_md": "# Report\n\n## Chapter 1\n\nbody\n## Chapter 6\n\nend",
            "council_persona_pool_size": 0,
            "active_council_persona_count": 0,
        }

    monkeypatch.setattr(runner_mod, "run_pipeline", fake_run_pipeline)
    stdout = io.StringIO()

    rc = serve_full("molecular diagnostic kit market adoption", report_path=tmp_path / "R.md", stdout=stdout)

    assert rc == 0
    events = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    progress = [event for event in events if event["event"] == "research_progress"]
    assert any(event["status"] == "source_evaluated" and event["accepted"] is True for event in progress)
    assert any(event["status"] == "knowledge_gap" and event["facet_id"] == "market" for event in progress)
