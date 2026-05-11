from src.evidence.artifact import EvidenceRef, Finding
from src.report.claim_matrix import build_claim_evidence_matrix
from src.research.planner import ResearchPlan
from src.research.refutation_loop import build_refutation_tasks, run_refutation_loop
from src.research.source_decision_ledger import SourceDecision, SourceDecisionLedger


def _plan() -> ResearchPlan:
    return ResearchPlan(
        brief_id="brief-refutation",
        queries=["topic counter evidence limitations"],
        query_routes=[
            {
                "route_id": "route-refute-1",
                "query": "topic counter evidence limitations",
                "facet_id": "topic",
                "intent": "refute",
                "source_class": "peer_reviewed",
                "backend": "scholar",
                "purpose": "test counter-evidence and limitations",
                "continue_reason": "skepticism pass required before readiness",
                "authority_requirement": "high",
                "acceptance_rules": ["must corroborate before high-confidence support"],
            }
        ],
    )


def _ref(source_id: str) -> EvidenceRef:
    return EvidenceRef(
        id=source_id,
        source_url=f"https://doi.org/10.5555/{source_id}",
        source_title="Traceable validation source",
        quote="traceable validation quote",
        source_grade="A",
        provenance={"kind": "paper", "source_role": "core_evidence"},
    )


def _decision(source_id: str, *, accepted: bool = True) -> SourceDecision:
    return SourceDecision(
        source_id=source_id,
        route_id="route-refute-1",
        raw_title="Traceable validation source",
        raw_url=f"https://doi.org/10.5555/{source_id}",
        canonical_id=f"10.5555/{source_id}" if accepted else None,
        canonical_url=f"https://doi.org/10.5555/{source_id}" if accepted else None,
        identifier_kind="doi" if accepted else "unknown",
        source_kind="paper",
        source_role="core_evidence",
        authority_level="high",
        accepted=accepted,
        decision="accepted" if accepted else "needs_review",
        relevance_score=0.9,
        reason="test decision",
        rejection_codes=() if accepted else ("canonical_identity_unresolved",),
        quote_present=True,
        locator_present=True,
        resolver_status="resolved" if accepted else "redirect_only",
    )


def test_builds_refutation_task_from_route_and_material_claim() -> None:
    ref = _ref("accepted")
    findings = [Finding("material claim", [ref], confidence=0.9)]
    ledger = SourceDecisionLedger((_decision("accepted"),))
    matrix = build_claim_evidence_matrix(findings, [ref], source_decision_ledger=ledger)

    tasks = build_refutation_tasks(_plan(), claim_matrix=matrix, source_decision_ledger=ledger)

    assert any(task.route_id == "route-refute-1" for task in tasks)
    assert any(task.claim == "material claim" for task in tasks)
    assert all(task.to_dict()["task_id"] for task in tasks)


def test_refutation_loop_records_unresolved_gap_for_insufficient_sources() -> None:
    ref = _ref("blocked")
    findings = [Finding("material claim", [ref], confidence=0.9)]
    ledger = SourceDecisionLedger((_decision("blocked", accepted=False),))
    matrix = build_claim_evidence_matrix(findings, [ref], source_decision_ledger=ledger)

    report = run_refutation_loop(_plan(), claim_matrix=matrix, source_decision_ledger=ledger)

    assert report.readiness == "blocked"
    assert report.unresolved_gap_count >= 1
    assert "insufficient_sources" in {result.decision for result in report.results}
    assert "unresolved_gap_recorded" in [event["status"] for event in report.events]


def test_refutation_loop_does_not_false_ready_when_blocked() -> None:
    ref = _ref("blocked")
    ledger = SourceDecisionLedger((_decision("blocked", accepted=False),))
    matrix = build_claim_evidence_matrix([Finding("unsupported material claim", [ref], confidence=0.95)], [ref], source_decision_ledger=ledger)

    report = run_refutation_loop(_plan(), claim_matrix=matrix, source_decision_ledger=ledger)

    assert report.summary()["readiness"] == "blocked"
    assert report.summary()["unresolved_gap_count"] > 0
    assert report.summary()["reason"] != "refutation pass completed without detected contradiction"
