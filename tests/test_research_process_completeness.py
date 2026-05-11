import json

from src.research.process_completeness import ProcessCompletenessInput, score_process_completeness


def _complete_input() -> ProcessCompletenessInput:
    return ProcessCompletenessInput(
        query_route_ledger={"route_count": 2, "routes": [{"route_id": "qr1"}]},
        source_decision_summary={"decision_count": 3, "accepted_count": 2},
        claim_evidence_summary={"passed": True, "row_count": 2, "supported_count": 2},
        refutation_loop_summary={"readiness": "completed", "task_count": 1},
        evidence_ledger_readiness="ready",
        evidence_ledger_metrics={"accepted_source_ratio": 1.0},
        research_readiness_decision={"readiness": "ready", "stop_state": "before_council"},
        progress_events=(
            {"status": "research_plan_ready"},
            {"status": "searching"},
            {"status": "source_decision_ledger_built"},
            {"status": "source_decision"},
        ),
    )


def test_process_completeness_complete_when_all_artifact_and_event_steps_present():
    decision = score_process_completeness(_complete_input())

    assert decision.readiness == "complete"
    assert decision.score == 1.0
    assert decision.missing_steps == ()
    assert "source_decision_ledger" in decision.present_steps


def test_process_completeness_missing_source_decision_is_blocking_and_stable():
    base = _complete_input()
    decision = score_process_completeness(
        ProcessCompletenessInput(
            query_route_ledger=base.query_route_ledger,
            source_decision_summary={},
            claim_evidence_summary=base.claim_evidence_summary,
            refutation_loop_summary=base.refutation_loop_summary,
            evidence_ledger_readiness=base.evidence_ledger_readiness,
            evidence_ledger_metrics=base.evidence_ledger_metrics,
            research_readiness_decision=base.research_readiness_decision,
            progress_events=base.progress_events,
        )
    )

    assert decision.readiness == "blocked"
    assert "source_decision_ledger" in decision.missing_steps
    assert decision.score < 1.0


def test_process_completeness_empty_event_stream_cannot_score_complete():
    base = _complete_input()
    decision = score_process_completeness(
        ProcessCompletenessInput(
            query_route_ledger=base.query_route_ledger,
            source_decision_summary=base.source_decision_summary,
            claim_evidence_summary=base.claim_evidence_summary,
            refutation_loop_summary=base.refutation_loop_summary,
            evidence_ledger_readiness=base.evidence_ledger_readiness,
            evidence_ledger_metrics=base.evidence_ledger_metrics,
            research_readiness_decision=base.research_readiness_decision,
            progress_events=(),
        )
    )

    assert decision.readiness == "partial"
    assert "research_plan_event" in decision.missing_steps
    assert "searching_event" in decision.missing_steps
    assert "source_decision_event" in decision.missing_steps


def test_process_completeness_payload_is_json_stable():
    payload = score_process_completeness(_complete_input()).to_dict()

    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    assert "research-process-completeness.v1" in encoded
    assert json.loads(encoded)["readiness"] == "complete"
