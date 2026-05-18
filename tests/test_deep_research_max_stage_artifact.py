import json

from src.muchanipo import terminal as terminal_mod
from src.research.deep_research_max_artifact import (
    DEEP_RESEARCH_MAX_ARTIFACT_CONTRACT,
    DeepResearchMaxArtifactInput,
    build_deep_research_max_stage_artifact,
    deep_research_max_stage_artifact_contract_report,
)


def _progress_events():
    return (
        {"status": "research_plan_ready"},
        {"status": "searching"},
        {"status": "source_decision_ledger_built"},
        {"status": "source_decision"},
    )


def _ready_input(**overrides) -> DeepResearchMaxArtifactInput:
    base = {
        "brief_id": "brief-generic",
        "research_agenda": {
            "questions": ["What decision must this research support?"],
            "decision_criteria": ["source quality", "claim traceability"],
        },
        "query_route_ledger": {"route_count": 2, "routes": [{"route_id": "route-1"}]},
        "source_audit_summary": {"passed": True},
        "source_decision_summary": {
            "decision_count": 3,
            "accepted_count": 2,
            "needs_review_count": 0,
            "blocking_unresolved_canonical_count": 0,
            "ledger_ref": "artifact:source-decision-ledger",
            "accepted_source_refs": ["source:accepted:1", "source:accepted:2"],
        },
        "claim_evidence_summary": {
            "passed": True,
            "row_count": 2,
            "supported_count": 2,
            "unsupported_count": 0,
            "supported_ratio": 1.0,
            "matrix_ref": "artifact:claim-evidence-matrix",
            "evidence_refs": ["claim:1", "claim:2"],
        },
        "evidence_ledger_readiness": "ready",
        "evidence_ledger_metrics": {
            "accepted_source_ratio": 1.0,
            "expected_claim_traceability_score": 1.0,
        },
        "refutation_loop_readiness": "completed",
        "refutation_loop_summary": {"readiness": "completed", "task_count": 1},
        "max_plus_benchmark_decision": "keep",
        "max_plus_benchmark_metrics": {"expected_claim_recall": 1.0},
        "progress_events": _progress_events(),
        "phase_trace": (
            {"index": 1, "phase": "route", "status": "completed"},
            {"index": 2, "phase": "read", "status": "completed"},
        ),
        "usage_ledger": {
            "total_tokens": 1200,
            "total_input_tokens": 400,
            "total_output_tokens": 300,
            "total_tool_use_tokens": 350,
            "total_thought_tokens": 150,
        },
    }
    base.update(overrides)
    return DeepResearchMaxArtifactInput(**base)


def _output_by_id(artifact, artifact_id):
    for item in artifact["outputs"]:
        if item.get("artifact_id") == artifact_id:
            return item
    raise AssertionError(f"missing output artifact {artifact_id}")


def test_ready_deep_research_max_artifact_exposes_scoring_and_runtime_evidence():
    artifact = build_deep_research_max_stage_artifact(_ready_input())

    assert artifact["stage_id"] == "deep_research_max"
    assert artifact["status"] == "completed"
    assert "legacy_stage" not in artifact
    assert artifact["metadata"]["specific_contract"] == DEEP_RESEARCH_MAX_ARTIFACT_CONTRACT
    assert (
        "does not represent or reproduce private provider internals"
        in artifact["metadata"]["claim_boundary"]
    )
    assert artifact["progress_percent"] == 100.0
    assert artifact["source_refs"] == [
        "artifact:source-decision-ledger",
        "source:accepted:1",
        "source:accepted:2",
    ]
    assert artifact["evidence_refs"] == [
        "artifact:claim-evidence-matrix",
        "claim:1",
        "claim:2",
    ]
    assert artifact["cost"]["usage_ledger"]["total_tool_use_tokens"] == 350
    assert artifact["time"]["client_timeout_seconds"] == 3600
    assert artifact["metrics"]["process_completeness_score"] == 1.0
    assert artifact["metrics"]["source_decision_accepted_count"] == 2
    assert artifact["hermes_scoring"]["score"] == 5.0
    assert artifact["hermes_scoring"]["readiness"] == "ready"

    agenda_output = _output_by_id(artifact, "research_agenda")
    assert agenda_output["present"] is True
    assert agenda_output["summary"]["decision_criteria"] == [
        "source quality",
        "claim traceability",
    ]

    runtime_output = _output_by_id(artifact, "runtime_contract")
    assert runtime_output["payload"]["execution_mode"] == "background_async_max"
    assert "content.delta:thought_summary" in runtime_output["payload"]["stream_event_types"]

    phase_output = _output_by_id(artifact, "phase_trace")
    assert phase_output["trace_kind"] == "observed"
    assert phase_output["items"][0]["status"] == "completed"


def test_zero_accepted_sources_blocks_before_downstream_synthesis():
    artifact = build_deep_research_max_stage_artifact(
        _ready_input(
            source_decision_summary={
                "decision_count": 2,
                "accepted_count": 0,
                "needs_review_count": 0,
                "blocking_unresolved_canonical_count": 0,
            },
            claim_evidence_summary={
                "passed": True,
                "row_count": 1,
                "supported_count": 1,
                "supported_ratio": 1.0,
            },
        )
    )

    assert artifact["status"] == "blocked"
    assert artifact["blockers"][0]["code"] == "blocked_no_acceptable_sources"
    assert artifact["human_decision"]["required"] is True
    assert artifact["human_decision"]["status"] == "pending"
    assert artifact["retry"]["retryable"] is True
    assert "blocked_no_acceptable_sources" in artifact["hermes_scoring"]["issues"]


def test_missing_visible_process_step_blocks_even_when_quality_gate_is_ready():
    artifact = build_deep_research_max_stage_artifact(_ready_input(query_route_ledger={}))

    completeness = _output_by_id(artifact, "research_process_completeness")["payload"]

    assert artifact["status"] == "blocked"
    assert artifact["blockers"][0]["code"] == "blocked_research_process_incomplete"
    assert "query_route_ledger" in completeness["missing_steps"]
    assert artifact["human_decision"]["required"] is False


def test_contract_report_is_exposed_from_cli_contracts_json():
    contract = deep_research_max_stage_artifact_contract_report()
    report = terminal_mod.json_contracts_report()

    assert contract["contract"] == DEEP_RESEARCH_MAX_ARTIFACT_CONTRACT
    assert contract["stage_id"] == "deep_research_max"
    assert "research_agenda" in contract["required_inputs"]
    assert "runtime_contract" in contract["required_outputs"]
    assert "blocked_fixture_overfit" in contract["failure_modes"]
    assert report["deep_research_max_stage_artifact_contract"] == contract


def test_deep_research_max_contract_does_not_embed_domain_fixture_terms():
    payload = json.dumps(
        deep_research_max_stage_artifact_contract_report(),
        ensure_ascii=False,
    ).lower()

    for forbidden in (
        "b-1",
        "b1",
        "strawberry",
        "딸기",
        "erwinia",
        "amylovora",
        "fire blight",
    ):
        assert forbidden not in payload
