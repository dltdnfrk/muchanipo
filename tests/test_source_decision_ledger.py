from __future__ import annotations

import json

from src.evidence.artifact import EvidenceRef, Finding
from src.research.citation_resolver import CitationCandidate, resolve_citation
from src.research.karpathy_autoresearch import build_research_quality_audit
from src.research.planner import ResearchPlan
from src.research.source_decision_ledger import build_source_decision_ledger, facet_gap_scheduler_report


def _plan() -> ResearchPlan:
    return ResearchPlan(
        brief_id="brief-generic",
        queries=["field validation sensitivity specificity assay peer reviewed"],
        evidence_targets=("peer reviewed field validation evidence",),
        expected_deliverables=("source decision ledger",),
        stop_conditions=("source audit complete",),
        topic_anchor="field validation sensitivity specificity assay",
        query_routes=(
            {
                "route_id": "route-peer-reviewed",
                "query": "field validation sensitivity specificity assay peer reviewed",
                "facet_id": "scientific",
                "intent": "confirmation",
                "source_class": "peer_reviewed",
                "backend": "scholar",
                "purpose": "confirm source-backed evidence",
                "authority_requirement": "high",
                "acceptance_rules": ["topic relevance", "stable canonical identity"],
            },
        ),
    )


def _ref(
    ref_id: str,
    *,
    title: str,
    url: str | None,
    quote: str | None,
    grade: str = "A",
    kind: str = "academic",
    route_id: str = "route-peer-reviewed",
) -> EvidenceRef:
    return EvidenceRef(
        id=ref_id,
        source_url=url,
        source_title=title,
        quote=quote,
        source_grade=grade,
        provenance={
            "kind": kind,
            "source_role": "primary",
            "authority_level": "high",
            "metadata": {
                "source_text": quote or "",
                "route_id": route_id,
                "query": "field validation sensitivity specificity assay peer reviewed",
            },
        },
    )


def test_citation_resolver_normalizes_doi_and_blocks_redirect_only_wrappers() -> None:
    resolved = resolve_citation(
        CitationCandidate(
            source_id="paper-1",
            title="Assay field validation doi:10.1234/ABC.DEF.2024",
            url="https://doi.org/10.1234/ABC.DEF.2024?utm_source=search",
            quote="Field validation sensitivity specificity assay evidence.",
            source_class="peer_reviewed",
            route_id="route-peer-reviewed",
        )
    )

    assert resolved.resolver_status == "resolved"
    assert resolved.identifier_kind == "doi"
    assert resolved.canonical_id == "10.1234/abc.def.2024"
    assert resolved.canonical_url == "https://doi.org/10.1234/abc.def.2024"

    redirect = resolve_citation(
        CitationCandidate(
            source_id="wrapped",
            title="Grounded result",
            url="https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQ",
            quote="Field validation sensitivity specificity assay evidence.",
            source_class="peer_reviewed",
            route_id="route-peer-reviewed",
        )
    )

    assert redirect.resolver_status == "redirect_only"
    assert redirect.canonical_id is None
    assert redirect.needs_review_reason


def test_source_decision_ledger_requires_stable_canonical_identity_for_accepted_support() -> None:
    plan = _plan()
    stable = _ref(
        "stable-doi",
        title="Field validation sensitivity specificity assay paper",
        url="https://doi.org/10.5555/Field.Validation.2024",
        quote="Field validation reports assay sensitivity and specificity in peer reviewed evidence.",
    )
    redirect = _ref(
        "redirect-only",
        title="Field validation sensitivity specificity assay wrapped result",
        url="https://vertexaisearch.cloud.google.com/grounding-api-redirect/opaque",
        quote="Field validation reports assay sensitivity and specificity in peer reviewed evidence.",
    )
    findings = [Finding(claim="Field validation reports assay sensitivity and specificity.", support=[stable, redirect], confidence=0.9)]
    audit = build_research_quality_audit(findings, plan)
    assert {item.source_id for item in audit.source_evaluations if item.accepted} == {"stable-doi", "redirect-only"}

    ledger = build_source_decision_ledger(findings, audit=audit, plan=plan)
    payload = ledger.to_dict()
    json.dumps(payload, ensure_ascii=False)

    by_id = {decision["source_id"]: decision for decision in payload["decisions"]}
    assert by_id["stable-doi"]["accepted"] is True
    assert by_id["stable-doi"]["decision"] == "accepted"
    assert by_id["stable-doi"]["canonical_id"] == "10.5555/field.validation.2024"
    assert by_id["redirect-only"]["accepted"] is False
    assert by_id["redirect-only"]["decision"] == "needs_review"
    assert "canonical_identity_unresolved" in by_id["redirect-only"]["rejection_codes"]
    assert payload["summary"]["accepted_count"] == 1
    assert payload["summary"]["needs_review_count"] == 1
    assert payload["summary"]["blocking_unresolved_canonical_count"] == 1


def test_source_decision_ledger_rejects_background_and_quote_missing_material_support() -> None:
    plan = _plan()
    background = _ref(
        "background-doi",
        title="Field validation sensitivity specificity assay background review",
        url="https://doi.org/10.7777/background.review",
        quote="Field validation sensitivity specificity assay background review.",
    )
    background.provenance["source_role"] = "background"
    no_quote = _ref(
        "no-quote-doi",
        title="Field validation sensitivity specificity assay paper",
        url="https://doi.org/10.8888/no.quote",
        quote=None,
    )
    findings = [Finding(claim="Field validation reports assay sensitivity and specificity.", support=[background, no_quote], confidence=0.9)]
    audit = build_research_quality_audit(findings, plan)

    ledger = build_source_decision_ledger(findings, audit=audit, plan=plan)
    by_id = {decision.source_id: decision for decision in ledger.decisions}

    assert by_id["background-doi"].accepted is False
    assert by_id["background-doi"].source_role == "background"
    assert "non_material_source_role" in by_id["background-doi"].rejection_codes
    assert by_id["no-quote-doi"].accepted is False
    assert "missing_quote" in by_id["no-quote-doi"].rejection_codes


def test_source_decision_summary_groups_decisions_by_route_facet_status() -> None:
    plan = _plan()
    accepted = _ref(
        "accepted-doi",
        title="Field validation sensitivity specificity assay paper",
        url="https://doi.org/10.9999/accepted.paper",
        quote="Field validation reports assay sensitivity and specificity in peer reviewed evidence.",
    )
    blocked = _ref(
        "blocked-wrapper",
        title="Field validation sensitivity specificity assay wrapped result",
        url="https://vertexaisearch.cloud.google.com/grounding-api-redirect/opaque",
        quote="Field validation reports assay sensitivity and specificity in peer reviewed evidence.",
    )
    rejected = _ref(
        "rejected-no-quote",
        title="Field validation sensitivity specificity assay paper",
        url="https://doi.org/10.4444/rejected.noquote",
        quote=None,
    )
    findings = [Finding(claim="Field validation reports assay sensitivity and specificity.", support=[accepted, blocked, rejected], confidence=0.9)]
    audit = build_research_quality_audit(findings, plan)

    summary = build_source_decision_ledger(findings, audit=audit, plan=plan).summary()

    assert summary["route_facet_counts"] == {"scientific": 3}
    assert summary["by_route_facet_id"]["scientific"] == {
        "decision_count": 3,
        "accepted_count": 1,
        "rejected_count": 1,
        "needs_review_count": 1,
        "blocking_unresolved_canonical_count": 1,
        "accepted_source_ids": ["accepted-doi"],
        "rejected_source_ids": ["rejected-no-quote"],
        "needs_review_source_ids": ["blocked-wrapper"],
        "route_ids": ["route-peer-reviewed"],
    }
    assert summary["route_facet_statuses"] == {"scientific": "needs_review"}


def test_facet_gap_scheduler_report_is_bounded_and_deterministic_from_generic_signals() -> None:
    planned_routes = [
        {"route_id": "route-canonical", "query": "generic topic canonical source", "facet_id": "canonical_sources", "intent": "primary_anchor_recall"},
        {"route_id": "route-background", "query": "generic topic background", "facet_id": "background_scope", "intent": "background"},
        {"route_id": "route-counter", "query": "generic topic counter evidence", "facet_id": "counter_evidence", "intent": "refutation"},
    ]
    source_decision_summary = {
        "by_route_facet_id": {
            "canonical_sources": {"decision_count": 2, "accepted_count": 1, "rejected_count": 1, "needs_review_count": 0},
            "background_scope": {"decision_count": 1, "accepted_count": 0, "rejected_count": 1, "needs_review_count": 0},
            "counter_evidence": {"decision_count": 1, "accepted_count": 0, "rejected_count": 0, "needs_review_count": 1},
        },
        "route_facet_statuses": {
            "canonical_sources": "satisfied",
            "background_scope": "gap",
            "counter_evidence": "needs_review",
        },
    }
    claim_coverage = {"unsupported_count": 1, "supported_ratio": 0.5}
    refutation_summary = {"readiness": "blocked", "unresolved_gap_count": 1}

    report = facet_gap_scheduler_report(
        planned_routes,
        source_decision_summary=source_decision_summary,
        claim_coverage=claim_coverage,
        refutation_summary=refutation_summary,
        max_followups=1,
    )

    assert report["status"] == "facet_gaps_pending"
    assert report["candidate_count"] == 2
    assert report["scheduled_count"] == 1
    assert report["scheduled_followups"] == [
        {
            "facet_id": "counter_evidence",
            "route_id": "route-counter",
            "query": "generic topic counter evidence",
            "intent": "refutation",
            "reason_codes": ["route_facet_needs_review", "claim_coverage_gap", "refutation_gap"],
            "priority": 0,
        }
    ]
    assert "erwinia" not in json.dumps(report).casefold()
    assert "b-1" not in json.dumps(report).casefold()
