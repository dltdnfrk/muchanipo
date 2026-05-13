import json

import pytest

from src.muchanipo import terminal as terminal_mod
from src.pipeline.goals_artifacts import (
    GOALS_STAGE_ARTIFACT_REQUIRED_KEYS,
    GOALS_STAGE_EVENT_REQUIRED_KEYS,
    GoalsFailureState,
    GoalsHumanDecisionState,
    GoalsStageArtifact,
    GoalsStageBlocker,
    GoalsStageMetrics,
    build_stage_artifact,
    goals_artifact_contract_report,
    goals_stage_artifact_contract_report,
    normalize_lifecycle_status,
    normalize_stage_event,
    normalize_stage_id,
    validate_canonical_stage_id,
)
from src.pipeline.goals_stages import PUBLIC_GOALS_STAGE_IDS


def test_goals_artifact_contract_report_defines_generic_schema_shape():
    report = goals_artifact_contract_report()

    assert report["schema_version"] == 1
    assert report["contract"] == "goals_stage_artifact_and_event"
    assert report["stage_ids"] == list(PUBLIC_GOALS_STAGE_IDS)
    assert report["lifecycle_statuses"] == [
        "pending",
        "running",
        "blocked",
        "completed",
        "failed",
    ]
    assert set(GOALS_STAGE_ARTIFACT_REQUIRED_KEYS) == set(report["artifact_required_keys"])
    assert set(GOALS_STAGE_EVENT_REQUIRED_KEYS) == set(report["event_required_keys"])
    assert report["normalization"]["legacy_preservation_field"] == "legacy_subactivity"


def test_stage_artifact_serializes_required_fields_and_metrics():
    artifact = build_stage_artifact(
        "deep_research_max",
        status="running",
        inputs={"brief_id": "brief-1"},
        outputs={"route_ledger": "runs/demo/routes.json"},
        evidence_refs=("claim:1",),
        source_refs=("doi:10.example/demo",),
        metrics=GoalsStageMetrics(
            progress_percent=42.5,
            cost={"tokens": 1200},
            time={"elapsed_seconds": 3.4},
            counters={"sources_seen": 7},
        ),
        legacy_subactivity={"legacy_stage": "research", "subactivity": "query_wave"},
    )

    assert set(GOALS_STAGE_ARTIFACT_REQUIRED_KEYS) <= set(artifact)
    assert artifact["stage_id"] == "deep_research_max"
    assert artifact["status"] == "running"
    assert artifact["inputs"] == {"brief_id": "brief-1"}
    assert artifact["outputs"] == {"route_ledger": "runs/demo/routes.json"}
    assert artifact["evidence_refs"] == ["claim:1"]
    assert artifact["source_refs"] == ["doi:10.example/demo"]
    assert artifact["metrics"]["progress_percent"] == 42.5
    assert artifact["metrics"]["cost"] == {"tokens": 1200}
    assert artifact["legacy_subactivity"]["legacy_stage"] == "research"


def test_canonical_id_validation_and_legacy_normalization_are_separate():
    assert validate_canonical_stage_id("llm_council") == "llm_council"
    assert normalize_stage_id("evidence") == "deep_research_max"
    assert normalize_stage_id("hitl_gate") == "plannotator_review"

    with pytest.raises(ValueError):
        validate_canonical_stage_id("research")
    with pytest.raises(KeyError):
        normalize_stage_id("unknown_legacy_stage")


def test_legacy_stage_event_normalizes_to_canonical_and_preserves_payload():
    event = normalize_stage_event(
        {
            "event": "stage_completed",
            "stage": "evidence",
            "phase": "source_gate",
            "status": "accepted",
            "progress": 1.0,
            "artifact_path": "runs/demo/evidence.json",
        }
    )

    assert set(GOALS_STAGE_EVENT_REQUIRED_KEYS) <= set(event)
    assert event["stage_id"] == "deep_research_max"
    assert event["status"] == "completed"
    assert event["progress_percent"] == 100.0
    assert event["artifact_ref"] == "runs/demo/evidence.json"
    assert event["legacy_subactivity"] == {
        "legacy_stage": "evidence",
        "legacy_event": "stage_completed",
        "subactivity": "source_gate",
    }
    assert event["payload"]["status"] == "accepted"


def test_internal_human_review_event_normalizes_to_review_stage():
    event = normalize_stage_event(
        {
            "event": "hitl_gate",
            "status": "needs_review",
            "gate": "report",
            "reviewer_mode": "human",
        }
    )

    assert event["stage_id"] == "plannotator_review"
    assert event["status"] == "blocked"
    assert event["legacy_subactivity"]["legacy_stage"] == "hitl_gate"
    assert event["payload"]["gate"] == "report"


def test_blocked_stage_artifact_requires_blocker_and_human_decision_state():
    blocker = GoalsStageBlocker(
        code="blocked_human_review_required",
        message="Reviewer approval is required.",
        required_action="wait_for_reviewer",
        human_decision_required=True,
    )
    decision = GoalsHumanDecisionState(
        required=True,
        status="pending",
        mode="plannotator",
        required_action="approve_or_reject",
    )
    artifact = build_stage_artifact(
        "plannotator_review",
        status="blocked",
        blockers=(blocker,),
        human_decision=decision,
    )

    assert artifact["status"] == "blocked"
    assert artifact["blockers"][0]["code"] == "blocked_human_review_required"
    assert artifact["blockers"][0]["human_decision_required"] is True
    assert artifact["human_decision"]["required"] is True
    assert artifact["human_decision"]["status"] == "pending"

    with pytest.raises(ValueError):
        GoalsStageArtifact(stage_id="plannotator_review", status="blocked")
    with pytest.raises(ValueError):
        GoalsHumanDecisionState(required=True, status="not_required")


def test_failure_and_status_validation_fail_closed():
    assert normalize_lifecycle_status("done") == "completed"
    assert normalize_lifecycle_status(source_event="error") == "failed"

    with pytest.raises(ValueError):
        GoalsStageArtifact(stage_id="idea_dump", status="failed")
    failed = GoalsStageArtifact(
        stage_id="idea_dump",
        status="failed",
        failure=GoalsFailureState(code="blocked_scope_conflict", terminal=True),
    )
    assert failed.as_dict()["failure"]["code"] == "blocked_scope_conflict"
    with pytest.raises(ValueError):
        GoalsStageMetrics(progress_percent=120)


def test_cli_contract_json_exposes_artifact_schema_additively():
    report = terminal_mod.json_contracts_report()

    assert report["goals_stage_artifact_contract"] == goals_stage_artifact_contract_report()
    assert report["goals_stage_artifact_contract"]["stage_ids"] == list(PUBLIC_GOALS_STAGE_IDS)


def test_artifact_contract_does_not_embed_fixture_topic_terms():
    payload = json.dumps(goals_artifact_contract_report(), ensure_ascii=False).lower()
    forbidden_terms = (
        "b-1",
        "b1",
        "strawberry",
        "딸기",
        "erwinia",
        "amylovora",
        "fire blight",
    )
    assert not any(term in payload for term in forbidden_terms)
