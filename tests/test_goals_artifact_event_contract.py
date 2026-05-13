import json

import pytest

from src.muchanipo.events import (
    KNOWN_EVENTS,
    goals_event_contract_report,
    normalize_goals_event,
)
from src.muchanipo import terminal as terminal_mod
from src.pipeline.goals_artifacts import (
    GOALS_HERMES_SCORING_FIELDS,
    GOALS_STAGE_ARTIFACT_FIELDS,
    GOALS_STAGE_STATUSES,
    build_goals_stage_artifact,
    goals_stage_artifact_contract_report,
    normalize_stage_artifact,
)
from src.pipeline.goals_stages import PUBLIC_GOALS_STAGE_IDS


def test_stage_artifact_contract_covers_all_scoring_inputs():
    contract = goals_stage_artifact_contract_report()

    assert contract["schema_version"] == 1
    assert contract["contract"] == "goals_stage_artifacts"
    assert contract["stage_ids"] == list(PUBLIC_GOALS_STAGE_IDS)
    assert contract["statuses"] == list(GOALS_STAGE_STATUSES)
    assert set(contract["artifact_fields"]) == set(GOALS_STAGE_ARTIFACT_FIELDS)
    assert contract["hermes_scoring_fields"] == list(GOALS_HERMES_SCORING_FIELDS)

    for stage_id, schema in contract["per_stage"].items():
        assert stage_id in PUBLIC_GOALS_STAGE_IDS
        assert schema["status"] == "not_started"
        assert schema["inputs"] == []
        assert schema["outputs"] == []
        assert schema["blockers"] == []
        assert schema["gates"] == []
        assert schema["evidence_refs"] == []
        assert schema["metrics"] == {}
        assert schema["hermes_scoring"] == {
            "score": None,
            "readiness": "unknown",
            "confidence": None,
            "rubric_version": None,
            "issues": [],
        }


def test_stage_artifact_normalizes_legacy_stage_and_preserves_payloads():
    artifact = normalize_stage_artifact(
        {
            "stage": "research",
            "status": "blocked",
            "inputs": [{"artifact_id": "brief", "path": "brief.yaml"}],
            "outputs": [{"artifact_id": "sources", "path": "sources.jsonl"}],
            "blockers": [{"kind": "hitl", "message": "needs approval"}],
            "gates": [{"gate_id": "source_gate", "status": "failed"}],
            "evidence_refs": [{"ref_id": "src-1", "uri": "https://example.test"}],
            "metrics": {"accepted_sources": 4},
            "hermes_scoring": {
                "score": 0.72,
                "readiness": "needs_fix",
                "confidence": 0.64,
                "rubric_version": "goals-loop2",
                "issues": ["source gate failed"],
            },
        }
    )

    assert artifact["stage_id"] == "deep_research_max"
    assert artifact["legacy_stage"] == "research"
    assert artifact["status"] == "blocked"
    assert artifact["inputs"][0]["artifact_id"] == "brief"
    assert artifact["outputs"][0]["artifact_id"] == "sources"
    assert artifact["blockers"][0]["kind"] == "hitl"
    assert artifact["gates"][0]["gate_id"] == "source_gate"
    assert artifact["evidence_refs"][0]["ref_id"] == "src-1"
    assert artifact["metrics"]["accepted_sources"] == 4
    assert artifact["hermes_scoring"]["readiness"] == "needs_fix"


def test_stage_artifact_rejects_unknown_status_and_unknown_stage():
    with pytest.raises(ValueError):
        build_goals_stage_artifact("idea_dump", status="paused")
    with pytest.raises(KeyError):
        build_goals_stage_artifact("unknown_stage")


def test_normalized_stage_events_accept_canonical_stage_ids_and_known_status_events():
    for event_name in ("stage_started", "stage_progress", "stage_blocked", "stage_completed", "stage_failed"):
        normalized = normalize_goals_event(
            {"event": event_name, "stage": "deep_research_max", "message": "ok"}
        )
        assert normalized["event"] == event_name
        assert normalized["stage"] == "deep_research_max"
        assert normalized["stage_id"] == "deep_research_max"
        assert normalized["metadata"]["message"] == "ok"
        assert event_name in KNOWN_EVENTS


def test_normalized_stage_events_map_legacy_stage_and_subactivity_to_metadata():
    started = normalize_goals_event(
        {"event": "stage_started", "stage": "research", "reference_step": 2}
    )
    assert started["event"] == "stage_started"
    assert started["stage"] == "deep_research_max"
    assert started["stage_id"] == "deep_research_max"
    assert started["metadata"]["legacy_stage"] == "research"
    assert started["metadata"]["reference_step"] == 2

    progress = normalize_goals_event(
        {"event": "research_progress", "stage": "research", "status": "collecting"}
    )
    assert progress["event"] == "stage_progress"
    assert progress["stage"] == "deep_research_max"
    assert progress["metadata"]["subactivity"] == "research_progress"
    assert progress["metadata"]["legacy_stage"] == "research"
    assert progress["metadata"]["status"] == "collecting"


def test_event_contract_is_exposed_from_contracts_json_report():
    report = terminal_mod.json_contracts_report()

    assert report["goals_stage_artifact_contract"] == goals_stage_artifact_contract_report()
    assert report["goals_event_contract"] == goals_event_contract_report()
    payload = json.dumps(report, ensure_ascii=False)
    assert "stage_blocked" in payload
    assert "hermes_scoring" in payload
