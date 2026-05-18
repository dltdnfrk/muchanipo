from __future__ import annotations

import json

import pytest

from src.council.parsers import RoundResult
from src.evidence.artifact import EvidenceRef
from src.hitl.plannotator_adapter import HITLResult
from src.hitl.plannotator_review_artifact import (
    PlannotatorReviewArtifactInput,
    build_plannotator_review_stage_artifact,
)
from src.muchanipo import terminal as terminal_mod
from src.pipeline.council_artifact import (
    LLMCouncilArtifactInput,
    build_llm_council_stage_artifact,
)
from src.pipeline.final_artifact import (
    FINAL_REPORT_ARTIFACT_CONTRACT,
    FinalReportArtifactInput,
    assert_final_report_artifact_ready_for_knowledge_write,
    build_final_report_stage_event,
    build_final_report_stage_artifact,
    final_report_event_metadata,
    final_report_payload_from_stage_artifact,
    final_report_stage_artifact_contract_report,
)
from src.pipeline.goals_artifacts import build_goals_stage_artifact
from src.pipeline.idea_to_council import _final_report_progress_event


def _output_by_id(artifact, artifact_id):
    for item in artifact["outputs"]:
        if item.get("artifact_id") == artifact_id:
            return item
    raise AssertionError(f"missing output artifact {artifact_id}")


def _evidence_ref(ref_id="ev-1"):
    return EvidenceRef(
        id=ref_id,
        source_url=f"https://example.test/{ref_id}",
        source_title=f"Source {ref_id}",
        quote="A source-backed observation.",
        source_grade="A",
        provenance={"kind": "test"},
    )


def _persona_payload():
    return {
        "schema_version": 1,
        "artifact_id": "persona_generation",
        "contract": "persona_generation_stage_artifact.v1",
        "persona_pool_id": "personas:final",
        "admitted_personas": [
            {"persona_id": "persona-1", "role": "operator", "evidence_refs_from_ontology": ["entity:1"]}
        ],
        "speaker_schedule": {"active_speakers": ["persona-1"]},
        "downstream_consumability": {
            "llm_council_ready": True,
            "reasons": [],
            "admitted_persona_count": 1,
        },
    }


def _round(key_claim="Council-backed final claim", evidence_ref_ids=None, body_claims=None):
    ids = ["ev-1"] if evidence_ref_ids is None else list(evidence_ref_ids)
    bodies = ["Follow-on claim"] if body_claims is None else list(body_claims)
    return RoundResult(
        layer_id="L1_market_sizing",
        chapter_title="Market context",
        key_claim=key_claim,
        body_claims=bodies,
        evidence_ref_ids=ids,
        confidence_score=0.84,
        framework="MECE",
    )


def _council_artifact(*, synthetic=False, key_claim="Council-backed final claim", empty_claims=False):
    effective_key = "" if empty_claims else key_claim
    effective_bodies = [] if empty_claims else None
    return build_llm_council_stage_artifact(
        LLMCouncilArtifactInput(
            persona_artifact=_persona_payload(),
            rounds=[_round(key_claim=effective_key, evidence_ref_ids=[] if synthetic else ["ev-1"], body_claims=effective_bodies)],
            evidence_refs=[_evidence_ref()],
            expected_layer_ids=["L1_market_sizing"],
            require_live=False,
        )
    )


def _council_artifact_without_claims():
    return build_llm_council_stage_artifact(
        LLMCouncilArtifactInput(
            persona_artifact=_persona_payload(),
            rounds=[
                RoundResult(
                    layer_id="L1_market_sizing",
                    chapter_title="Market context",
                    key_claim="",
                    body_claims=[],
                    evidence_ref_ids=["ev-1"],
                    confidence_score=0.84,
                    framework="MECE",
                )
            ],
            evidence_refs=[_evidence_ref()],
            expected_layer_ids=["L1_market_sizing"],
            require_live=False,
        )
    )


def _review_artifact(gate_name="report", status="approved", synthetic=False):
    return build_plannotator_review_stage_artifact(
        PlannotatorReviewArtifactInput(
            gate_name=gate_name,
            result=HITLResult(
                status=status,
                gate_id=f"{gate_name}-gate",
                path=f"plannotator://sessions/{gate_name}",
                synthetic=synthetic,
                decision_provenance={
                    "mode": "plannotator_http",
                    "source": "test",
                    "synthetic": synthetic,
                },
            ),
            mode="plannotator",
            target_artifact_refs=[f"state:{gate_name}"],
        )
    )


def _completed_upstream(stage_id):
    return build_goals_stage_artifact(
        stage_id,
        status="completed",
        outputs=[{"artifact_id": stage_id, "present": True}],
        gates=[{"gate_id": f"{stage_id}_gate", "status": "passed"}],
    )


def _upstreams(**overrides):
    base = {
        "deep_research_max": _completed_upstream("deep_research_max"),
        "plannotator_review": [
            _review_artifact("plan"),
            _review_artifact("evidence"),
            _review_artifact("report"),
        ],
        "ontology_extraction": _completed_upstream("ontology_extraction"),
        "persona_generation": _completed_upstream("persona_generation"),
        "llm_council": _council_artifact(),
    }
    base.update(overrides)
    return base


def _artifact_input(tmp_path, **overrides):
    base = {
        "report_id": "brief-final",
        "title": "Decision report",
        "report_markdown": "# Decision report\n\nSource-backed report body.\n",
        "output_dir": tmp_path,
        "upstream_artifacts": _upstreams(),
        "evidence_refs": [_evidence_ref()],
        "open_gaps": ["Quantify pricing sensitivity."],
        "gates": {
            "plan": {"status": "approved", "gate_id": "plan-gate"},
            "evidence": {"status": "approved", "gate_id": "evidence-gate"},
            "report": {"status": "approved", "gate_id": "report-gate"},
        },
        "reference_runtime_artifacts": {
            "gbrain": {
                "gbrain_runtime": {"valid": True, "event_ledger": [{"id": "evt-1"}]},
                "content_hash": "abc123",
            }
        },
        "obsidian_write_path": str(tmp_path / "Decision report.md"),
        "obsidian_write_attempted": True,
    }
    base.update(overrides)
    return FinalReportArtifactInput(**base)


def test_final_report_artifact_happy_path_writes_manifest_and_contract(tmp_path):
    artifact = build_final_report_stage_artifact(_artifact_input(tmp_path))
    payload = final_report_payload_from_stage_artifact(artifact)
    manifest = payload["artifact_manifest"]

    assert artifact["stage_id"] == "final_report_html_yaml"
    assert artifact["status"] == "completed"
    assert artifact["metadata"]["specific_contract"] == FINAL_REPORT_ARTIFACT_CONTRACT
    assert artifact["hermes_scoring"]["readiness"] == "ready"
    assert manifest["obsidian_write_status"] == "written"
    assert manifest["gate_statuses"]["plan"] == "approved"
    assert manifest["gate_statuses"]["knowledge_write"] == "passed"
    assert manifest["html_path"].endswith(".html")
    assert manifest["yaml_path"].endswith(".yaml")
    assert manifest["evidence_bundle_path"].endswith(".json")
    assert manifest["gbrain_record_path"].endswith(".json")
    for path_key in ("html_path", "yaml_path", "evidence_bundle_path", "gbrain_record_path"):
        assert (tmp_path / manifest[path_key].split("/")[-1]).exists()

    assert_final_report_artifact_ready_for_knowledge_write(artifact)


def test_upstream_blocker_refuses_final_report_and_blocks_knowledge_write(tmp_path):
    blocked_deep = build_goals_stage_artifact(
        "deep_research_max",
        status="blocked",
        blockers=[{"code": "blocked_no_acceptable_sources"}],
    )
    artifact = build_final_report_stage_artifact(
        _artifact_input(
            tmp_path,
            upstream_artifacts=_upstreams(deep_research_max=blocked_deep),
            obsidian_write_path="",
            obsidian_write_attempted=False,
        )
    )
    payload = final_report_payload_from_stage_artifact(artifact)

    assert artifact["status"] == "blocked"
    assert "blocked_final_upstream_artifact_not_ready" in {
        blocker["code"] for blocker in artifact["blockers"]
    }
    assert payload["artifact_manifest"]["gate_statuses"]["knowledge_write"] == "blocked"
    with pytest.raises(ValueError, match="blocked_final_upstream_artifact_not_ready"):
        assert_final_report_artifact_ready_for_knowledge_write(artifact)


def test_html_and_yaml_have_matching_final_bundle_fields(tmp_path):
    artifact = build_final_report_stage_artifact(_artifact_input(tmp_path))
    payload = final_report_payload_from_stage_artifact(artifact)
    manifest = payload["artifact_manifest"]

    html = (tmp_path / manifest["html_path"].split("/")[-1]).read_text(encoding="utf-8")
    html_bundle = json.loads(
        html.split('<script type="application/json" id="final-report-bundle">', 1)[1].split(
            "</script>", 1
        )[0]
    )
    yaml_bundle = json.loads((tmp_path / manifest["yaml_path"].split("/")[-1]).read_text(encoding="utf-8"))

    for key in ("central_claims", "source_ids", "evidence_ids", "verdict", "open_gaps", "blockers"):
        assert html_bundle[key] == yaml_bundle[key] == payload["bundle"][key]


def test_gbrain_and_obsidian_are_skipped_honestly_without_real_write_path(tmp_path):
    artifact = build_final_report_stage_artifact(
        _artifact_input(
            tmp_path,
            reference_runtime_artifacts={},
            obsidian_write_path="",
            obsidian_write_attempted=False,
        )
    )
    payload = final_report_payload_from_stage_artifact(artifact)
    manifest = payload["artifact_manifest"]

    assert artifact["status"] == "completed"
    assert manifest["gbrain_record_status"] == "skipped_unavailable"
    assert manifest["obsidian_write_status"] == "skipped_unavailable"
    assert manifest["gate_statuses"]["knowledge_write"] == "skipped_unavailable"


def test_live_mode_synthetic_council_artifact_blocks_final_write(tmp_path):
    artifact = build_final_report_stage_artifact(
        _artifact_input(
            tmp_path,
            upstream_artifacts=_upstreams(llm_council=_council_artifact(synthetic=True)),
            require_live=True,
            obsidian_write_path="",
            obsidian_write_attempted=False,
        )
    )

    assert artifact["status"] == "blocked"
    assert "blocked_final_live_synthetic_artifact" in {
        blocker["code"] for blocker in artifact["blockers"]
    }


def test_final_report_contract_exposed_and_fixture_agnostic():
    contract = final_report_stage_artifact_contract_report()
    report = terminal_mod.json_contracts_report()

    assert contract["contract"] == FINAL_REPORT_ARTIFACT_CONTRACT
    assert contract["stage_id"] == "final_report_html_yaml"
    assert "artifact_manifest" in contract["required_outputs"]
    assert report["final_report_html_yaml_stage_artifact_contract"] == contract

    payload = json.dumps(contract, ensure_ascii=False).lower()
    for forbidden in ("strawberry", "딸기", "erwinia", "amylovora", "fire blight"):
        assert forbidden not in payload
    for parity_claim in (
        "hachimi parity",
        "map-elites parity",
        "evoagentx parity",
        "mirofish parity",
        "nemotron parity",
    ):
        assert parity_claim not in payload


def test_final_claims_come_from_council_artifact_not_fixture_topic(tmp_path):
    artifact = build_final_report_stage_artifact(
        _artifact_input(
            tmp_path,
            title="strawberry fire blight market report",
            upstream_artifacts=_upstreams(
                llm_council=_council_artifact(key_claim="Council artifact claim")
            ),
        )
    )
    payload = final_report_payload_from_stage_artifact(artifact)

    assert payload["bundle"]["central_claims"] == ["Council artifact claim", "Follow-on claim"]
    joined_claims = " ".join(payload["bundle"]["central_claims"]).lower()
    assert "strawberry" not in joined_claims
    assert "fire blight" not in joined_claims


def test_no_central_claims_from_council_produces_blocker_and_blocks_knowledge_write(tmp_path):
    """Adversarial no-claim scenario: council reports ready (has rounds) but extracts to zero usable claims.
    Exercises the explicit blocked_final_no_central_claims injection + knowledge_write gate block.
    This covers a gap in pending/rejected/no-claim adversarial coverage for final_report.
    """
    artifact = build_final_report_stage_artifact(
        _artifact_input(
            tmp_path,
            upstream_artifacts=_upstreams(
                llm_council=_council_artifact(empty_claims=True)
            ),
        )
    )

    blocker_codes = {blocker["code"] for blocker in artifact["blockers"]}
    assert "blocked_final_no_central_claims" in blocker_codes
    assert artifact["status"] == "blocked"
    assert "blocked_final_council_not_ready" not in blocker_codes  # council itself was ready, final's extra check fired

    payload = final_report_payload_from_stage_artifact(artifact)
    manifest = payload["artifact_manifest"]
    assert manifest["gate_statuses"]["knowledge_write"] == "blocked"
    assert payload["downstream_consumability"]["knowledge_write_ready"] is False
    assert "blocked_final_no_central_claims" in payload["downstream_consumability"]["reasons"]

    with pytest.raises(ValueError, match="blocked_final_no_central_claims"):
        assert_final_report_artifact_ready_for_knowledge_write(artifact)

    # Also confirm central_claims is empty in the bundle (the root cause)
    assert payload["bundle"]["central_claims"] == []
    assert payload["bundle"]["verdict"] == "BLOCKED"


def test_blocked_final_report_event_exposes_manifest_gates_and_readiness(tmp_path):
    artifact_input = _artifact_input(
        tmp_path,
        gates={
            "plan": {"status": "approved", "gate_id": "plan-gate"},
            "evidence": {"status": "approved", "gate_id": "evidence-gate"},
            "report": {"status": "pending", "gate_id": "report-gate"},
        },
        upstream_artifacts=_upstreams(
            plannotator_review=[
                _review_artifact("plan"),
                _review_artifact("evidence"),
                _review_artifact("report", status="pending"),
            ],
        ),
        obsidian_write_path="",
        obsidian_write_attempted=False,
    )

    event = build_final_report_stage_event(artifact_input)
    metadata = event["metadata"]

    assert event["event"] == "stage_blocked"
    assert event["stage_id"] == "final_report_html_yaml"
    assert metadata["final_report_ready"] is False
    assert metadata["knowledge_write_ready"] is False
    assert metadata["gate_statuses"]["report"] == "pending"
    assert metadata["gate_statuses"]["knowledge_write"] == "blocked"
    assert metadata["evidence_bundle_path"].endswith(".json")
    assert metadata["gbrain_record_path"].endswith(".json")
    assert metadata["gbrain_record_status"] == "runtime_record_written"
    assert "blocked_final_gate_pending" in metadata["blocker_codes"]
    assert metadata["blocker_count"] == len(metadata["blocker_codes"])


def test_pipeline_final_report_progress_event_preserves_blocked_manifest_fields(tmp_path):
    artifact = build_final_report_stage_artifact(
        _artifact_input(
            tmp_path,
            gates={
                "plan": {"status": "approved", "gate_id": "plan-gate"},
                "evidence": {"status": "approved", "gate_id": "evidence-gate"},
                "report": {"status": "rejected", "gate_id": "report-gate"},
            },
            obsidian_write_path="",
            obsidian_write_attempted=False,
        )
    )

    progress = _final_report_progress_event(artifact)

    assert progress["event"] == "stage_blocked"
    assert progress["final_report_ready"] is False
    assert progress["knowledge_write_ready"] is False
    assert progress["gate_statuses"]["report"] == "rejected"
    assert progress["gate_statuses"]["knowledge_write"] == "blocked"
    assert progress["evidence_bundle_path"].endswith(".json")
    assert progress["gbrain_record_path"].endswith(".json")
    assert progress["gbrain_record_status"] == "runtime_record_written"
    assert "blocked_final_report_gate_rejected" in progress["blocker_codes"]
    assert progress["blocker_count"] == len(progress["blocker_codes"])
    for key, value in final_report_event_metadata(artifact).items():
        assert progress[key] == value


def test_no_claim_final_report_event_is_blocked_without_topic_reconstruction(tmp_path):
    event = build_final_report_stage_event(
        _artifact_input(
            tmp_path,
            title="strawberry fire blight market report",
            upstream_artifacts=_upstreams(llm_council=_council_artifact_without_claims()),
            obsidian_write_path="",
            obsidian_write_attempted=False,
        )
    )
    metadata = event["metadata"]

    assert event["event"] == "stage_blocked"
    assert metadata["central_claim_count"] == 0
    assert metadata["final_report_ready"] is False
    assert "blocked_final_no_central_claims" in metadata["blocker_codes"]
