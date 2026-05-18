import json

from src.hitl.plannotator_adapter import HITLResult
from src.hitl.plannotator_review_artifact import (
    PLANNOTATOR_REVIEW_ARTIFACT_CONTRACT,
    PlannotatorReviewArtifactInput,
    build_plannotator_review_stage_artifact,
    build_plannotator_review_stage_event,
    plannotator_review_stage_artifact_contract_report,
)
from src.muchanipo import terminal as terminal_mod


def test_real_approved_review_builds_completed_canonical_stage_artifact():
    result = HITLResult(
        status="approved",
        annotations=[{"type": "comment", "target": "plan", "instruction": "Looks good."}],
        comments=["Looks good."],
        gate_id="sess-plan",
        path="plannotator://sessions/sess-plan",
        synthetic=False,
        reviewer_id="reviewer-1",
        decision_provenance={"mode": "plannotator_http", "source": "plannotator_client"},
    )

    artifact = build_plannotator_review_stage_artifact(
        PlannotatorReviewArtifactInput(
            gate_name="plan",
            result=result,
            mode="plannotator",
            live_mode=True,
            target_artifact_refs=["artifact:research-plan"],
            applied_deltas=[{"target": "plan.scope", "operation": "accept"}],
        )
    )
    event = build_plannotator_review_stage_event(
        PlannotatorReviewArtifactInput(
            gate_name="plan",
            result=result,
            mode="plannotator",
            live_mode=True,
        )
    )

    assert artifact["stage_id"] == "plannotator_review"
    assert artifact["status"] == "completed"
    assert artifact["human_decision"]["status"] == "approved"
    assert artifact["human_decision"]["synthetic"] is False
    assert artifact["metrics"]["annotation_count"] == 1
    assert artifact["metrics"]["applied_delta_count"] == 1
    assert artifact["source_refs"] == ["plannotator://sessions/sess-plan"]
    assert artifact["hermes_scoring"]["readiness"] == "approved"
    assert event["event"] == "stage_completed"
    assert event["stage_id"] == "plannotator_review"
    assert event["metadata"]["annotation_count"] == 1


def test_synthetic_approval_blocks_live_review_artifact():
    result = HITLResult(
        status="approved",
        gate_id="plan-auto",
        path="synthetic://auto-approve/plan",
        synthetic=True,
    )

    artifact = build_plannotator_review_stage_artifact(
        PlannotatorReviewArtifactInput(
            gate_name="plan",
            result=result,
            mode="auto_approve",
            live_mode=True,
        )
    )

    assert artifact["stage_id"] == "plannotator_review"
    assert artifact["status"] == "blocked"
    assert artifact["metrics"]["review_state"] == "blocked"
    assert artifact["blockers"][0]["code"] == "blocked_synthetic_hitl_live_mode"
    assert artifact["human_decision"]["synthetic"] is True
    assert artifact["failure_semantics"]["retryable"] is False


def test_changes_requested_review_is_resumable_with_annotation_count():
    result = HITLResult(
        status="changes_requested",
        annotations=[
            {"type": "edit", "target": "report.summary", "instruction": "Narrow the claim."}
        ],
        comments=["Narrow the claim."],
        gate_id="sess-report",
        path="plannotator://sessions/sess-report",
    )

    artifact = build_plannotator_review_stage_artifact(
        PlannotatorReviewArtifactInput(
            gate_name="report",
            result=result,
            mode="plannotator",
            rejected_deltas=[{"target": "report.summary", "reason": "needs evidence"}],
            resume_token="resume-report-1",
        )
    )
    resumption = next(item for item in artifact["outputs"] if item["artifact_id"] == "resumption")

    assert artifact["status"] == "blocked"
    assert artifact["metrics"]["review_state"] == "changes_requested"
    assert artifact["metrics"]["annotation_count"] == 1
    assert artifact["blockers"][0]["code"] == "blocked_annotation_conflict"
    assert artifact["retry"]["retryable"] is True
    assert resumption == {
        "artifact_id": "resumption",
        "resumable": True,
        "resume_token": "resume-report-1",
    }


def test_live_approved_review_without_session_path_blocks_as_missing_provenance():
    result = HITLResult(status="approved", gate_id="manual-plan", synthetic=False)

    artifact = build_plannotator_review_stage_artifact(
        PlannotatorReviewArtifactInput(
            gate_name="plan",
            result=result,
            mode="manual",
            live_mode=True,
        )
    )

    assert artifact["status"] == "blocked"
    assert artifact["blockers"][0]["code"] == "blocked_missing_review_provenance"
    assert artifact["human_decision"]["required_action"] == (
        "persist_review_session_path_and_decision_provenance"
    )


def test_plannotator_review_contract_is_exposed_and_fixture_isolated():
    contract = plannotator_review_stage_artifact_contract_report()
    report = terminal_mod.json_contracts_report()
    payload = json.dumps(contract, ensure_ascii=False).lower()

    assert contract["contract"] == PLANNOTATOR_REVIEW_ARTIFACT_CONTRACT
    assert contract["stage_id"] == "plannotator_review"
    assert "changes_requested" in contract["review_states"]
    assert report["plannotator_review_stage_artifact_contract"] == contract
    for forbidden in ("b-1", "b1", "strawberry", "딸기", "erwinia", "amylovora", "fire blight"):
        assert forbidden not in payload
