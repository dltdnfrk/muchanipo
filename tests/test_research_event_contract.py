from __future__ import annotations

import pytest

from src.research.event_contract import (
    assert_research_event_contract,
    validate_research_event_contract,
)


BASE = {
    "event": "research_progress",
    "stage": "research",
    "status": "research_plan_ready",
    "research_session_id": "research-session-a",
    "app_run_id": "run-a",
    "memory_policy": "no_implicit_cross_session_memory",
    "topic_anchor": "generic diagnostics question",
}


def test_valid_planned_search_source_and_quality_events_pass() -> None:
    plan_event = {**BASE, "queries": ["q1"], "query_count": 1, "query_routes": [{"route_id": "r1"}]}
    search_event = {
        **BASE,
        "status": "searching",
        "query": "q1",
        "query_index": 1,
        "query_count": 1,
        "route_id": "r1",
    }
    source_event = {
        **BASE,
        "status": "source_decision",
        "source_id": "src-1",
        "route_id": "r1",
        "resolver_status": "resolved",
        "decision": "accepted",
        "reason": "canonical material source",
    }
    quality_event = {
        **BASE,
        "event": "research_quality_needs_review",
        "stage": "quality_gate",
        "status": "blocked_before_council",
        "research_quality_readiness": "blocked",
        "research_readiness_decision": {
            "readiness": "blocked",
            "stop_state": "blocked_before_council",
            "reasons": ["source_decision_summary.blocking_unresolved_canonical_count=1"],
        },
        "research_process_completeness": {"score": 1.0, "readiness": "complete", "missing_steps": []},
    }

    for event in (plan_event, search_event, source_event, quality_event):
        decision = validate_research_event_contract(event)
        assert decision.in_scope is True
        assert decision.valid is True
        assert assert_research_event_contract(event) == event


def test_missing_session_fields_fail_with_stable_codes() -> None:
    event = {k: v for k, v in BASE.items() if k not in {"research_session_id", "app_run_id"}}
    event.update({"queries": ["q1"], "query_count": 1})

    decision = validate_research_event_contract(event)

    assert decision.valid is False
    assert "research_session_id" in decision.missing_fields
    assert "app_run_id" in decision.missing_fields
    assert "missing:research_session_id" in decision.error_codes
    assert "missing:app_run_id" in decision.error_codes
    with pytest.raises(ValueError, match="missing:research_session_id"):
        assert_research_event_contract(event)


def test_status_specific_missing_fields_fail_deterministically() -> None:
    source_event = {**BASE, "status": "source_decision", "source_id": "src-1", "route_id": "r1"}

    decision = validate_research_event_contract(source_event)

    assert decision.valid is False
    assert "decision" in decision.missing_fields
    assert "reason" in decision.missing_fields
    assert "canonical_id_or_resolver_status" in decision.missing_fields
    assert decision.error_codes == (
        "missing:decision",
        "missing:reason",
        "missing:canonical_id_or_resolver_status",
    )


def test_smart_research_progress_events_require_ui_decision_fields() -> None:
    ledger_event = {
        **BASE,
        "stage": "quality_gate",
        "status": "source_decision_ledger_built",
        "by_route_facet_id": {"canonical_sources": {"accepted_count": 1}},
        "route_facet_statuses": {"canonical_sources": "satisfied"},
    }
    claim_event = {
        **BASE,
        "stage": "quality_gate",
        "status": "claim_evidence_gate",
        "claim_verification_summary": {"row_count": 1, "passed": True},
        "citation_verification_summary": {"supporting_source_count": 1},
    }
    facet_gap_event = {
        **BASE,
        "stage": "quality_gate",
        "status": "facet_gap_scheduler_report",
        "facet_gap_scheduler_report": {"status": "complete", "scheduled_followups": []},
        "by_route_facet_id": {"canonical_sources": {"accepted_count": 1}},
        "route_facet_statuses": {"canonical_sources": "satisfied"},
        "claim_verification_summary": {"row_count": 1, "passed": True},
        "citation_verification_summary": {"supporting_source_count": 1},
    }

    for event in (ledger_event, claim_event, facet_gap_event):
        decision = validate_research_event_contract(event)
        assert decision.valid is True, decision.to_dict()

    invalid_facet_gap_event = {k: v for k, v in facet_gap_event.items() if k != "facet_gap_scheduler_report"}
    decision = validate_research_event_contract(invalid_facet_gap_event)
    assert decision.valid is False
    assert "facet_gap_scheduler_report" in decision.missing_fields
    assert "missing:facet_gap_scheduler_report" in decision.error_codes


def test_unknown_non_research_app_events_are_out_of_scope() -> None:
    event = {"event": "report_chunk", "markdown": "hello"}

    decision = validate_research_event_contract(event)

    assert decision.in_scope is False
    assert decision.valid is True
    assert assert_research_event_contract(event) == event
