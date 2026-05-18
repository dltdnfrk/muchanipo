from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.council.parsers import RoundResult
from src.evidence.artifact import EvidenceRef
from src.muchanipo import terminal as terminal_mod
from src.pipeline.council_artifact import (
    LLMCouncilArtifactInput,
    assert_council_artifact_ready_for_final_report,
    build_llm_council_stage_artifact,
    llm_council_stage_artifact_contract_report,
)
from src.pipeline.idea_to_council import _round_digests


def _output_by_id(artifact, artifact_id):
    for item in artifact["outputs"]:
        if item.get("artifact_id") == artifact_id:
            return item
    raise AssertionError(f"missing output artifact {artifact_id}")


def _ready_persona_artifact():
    return {
        "schema_version": 1,
        "artifact_id": "persona_generation",
        "contract": "persona_generation_stage_artifact.v1",
        "persona_pool_id": "personas:test",
        "admitted_personas": [
            {
                "persona_id": "persona-001",
                "role": "domain_expert",
                "evidence_refs_from_ontology": ["entity:operator", "source:interview-1"],
            }
        ],
        "speaker_schedule": {"active_speakers": ["persona-001"]},
        "downstream_consumability": {
            "llm_council_ready": True,
            "reasons": [],
            "admitted_persona_count": 1,
        },
    }


def _unready_persona_artifact():
    payload = _ready_persona_artifact()
    payload["admitted_personas"] = []
    payload["speaker_schedule"] = {"active_speakers": []}
    payload["downstream_consumability"] = {
        "llm_council_ready": False,
        "reasons": ["min_council_size_not_met"],
        "admitted_persona_count": 0,
    }
    return payload


def _round(evidence_ref_ids=None, key_claim="Council claim"):
    return RoundResult(
        layer_id="L1_market_sizing",
        chapter_title="Market context",
        key_claim=key_claim,
        body_claims=["Body claim"],
        evidence_ref_ids=list(evidence_ref_ids or []),
        confidence_score=0.82,
        framework="MECE Tree",
    )


def _evidence_ref(ref_id="ref-1"):
    return EvidenceRef(
        id=ref_id,
        source_url="https://doi.org/10.1234/source",
        source_title="Source title",
        quote="Source quote",
        source_grade="A",
        provenance={"kind": "openalex"},
    )


def _payload(artifact):
    return _output_by_id(artifact, "llm_council")["payload"]


def test_canonical_council_artifact_builder_emits_contract_and_readiness():
    artifact = build_llm_council_stage_artifact(
        LLMCouncilArtifactInput(
            persona_artifact=_ready_persona_artifact(),
            rounds=[_round(["ref-1"])],
            turn_transcript=[
                {
                    "event": "council_provider_call_done",
                    "round": 1,
                    "layer": "L1_market_sizing",
                    "council_stage": "chairman",
                    "provider": "fixture-provider",
                    "model": "fixture-model",
                }
            ],
            protocol_traces_by_round={1: {"runtime": "clean-room local social simulation protocol", "phase_count": 3}},
            evidence_refs=[_evidence_ref()],
            expected_layer_ids=["L1_market_sizing"],
            council_session_id="council-test",
        )
    )

    payload = _payload(artifact)

    assert artifact["stage_id"] == "llm_council"
    assert artifact["status"] == "completed"
    assert artifact["metadata"]["specific_contract"] == "llm_council_stage_artifact.v1"
    assert artifact["metrics"]["final_report_ready"] is True
    assert payload["artifact_id"] == "llm_council"
    assert payload["downstream_consumability"]["final_report_ready"] is True
    assert payload["round_digests"][0]["evidence_association"] == "direct"
    assert payload["round_digests"][0]["evidence_ref_ids"] == ["ref-1"]
    assert payload["provider_model_provenance"][0]["provider"] == "fixture-provider"
    assert payload["provider_model_provenance"][0]["model"] == "fixture-model"
    assert payload["turn_protocol_summary"]["protocol_runtimes"] == [
        "clean-room local social simulation protocol"
    ]
    assert_council_artifact_ready_for_final_report(artifact)


def test_unready_persona_artifact_refuses_final_report_readiness():
    artifact = build_llm_council_stage_artifact(
        LLMCouncilArtifactInput(
            persona_artifact=_unready_persona_artifact(),
            rounds=[_round(["ref-1"])],
            evidence_refs=[_evidence_ref()],
            expected_layer_ids=["L1_market_sizing"],
        )
    )
    payload = _payload(artifact)

    assert artifact["status"] == "blocked"
    assert "blocked_council_persona_pool_rejected" in {
        blocker["code"] for blocker in artifact["blockers"]
    }
    assert payload["downstream_consumability"]["final_report_ready"] is False
    with pytest.raises(ValueError, match="blocked_council_persona_pool_rejected"):
        assert_council_artifact_ready_for_final_report(artifact)


def test_live_mode_missing_required_round_blocks_honestly():
    artifact = build_llm_council_stage_artifact(
        LLMCouncilArtifactInput(
            persona_artifact=_ready_persona_artifact(),
            rounds=[],
            evidence_refs=[_evidence_ref()],
            expected_layer_ids=["L1_market_sizing"],
            require_live=True,
            mode="live",
        )
    )
    payload = _payload(artifact)

    assert artifact["status"] == "blocked"
    assert "blocked_council_live_output_empty" in {
        blocker["code"] for blocker in artifact["blockers"]
    }
    assert payload["round_integrity"]["empty_live_layer_ids"] == ["L1_market_sizing"]
    assert payload["downstream_consumability"]["final_report_ready"] is False


def test_evidence_fallback_is_marked_synthetic_aggregate_not_silent():
    artifact = build_llm_council_stage_artifact(
        LLMCouncilArtifactInput(
            persona_artifact=_ready_persona_artifact(),
            rounds=[_round([])],
            evidence_refs=[_evidence_ref("ref-aggregate")],
            expected_layer_ids=["L1_market_sizing"],
            require_live=False,
        )
    )
    payload = _payload(artifact)
    round_payload = payload["round_digests"][0]

    assert artifact["status"] == "completed"
    assert round_payload["evidence_ref_ids"] == ["ref-aggregate"]
    assert round_payload["direct_evidence_ref_ids"] == []
    assert round_payload["evidence_association"] == "synthetic_aggregate"
    assert round_payload["synthetic_fallback"] is True
    assert payload["synthetic_fallback_markers"][0]["type"] == "synthetic_aggregate_evidence"
    assert payload["downstream_consumability"]["final_report_ready"] is True


def test_report_round_digest_no_longer_silently_assigns_all_evidence_to_empty_round():
    digests = _round_digests(
        SimpleNamespace(rounds=[_round([])]),
        [_evidence_ref("ref-aggregate")],
    )

    assert digests[0].layer_id == "L1_market_sizing"
    assert digests[0].evidence_ref_ids == ["ref-aggregate"]
    assert digests[0].evidence_association == "synthetic_aggregate"
    assert digests[0].synthetic_fallback is True


def test_final_report_ready_is_derived_from_plateau_requirement():
    artifact = build_llm_council_stage_artifact(
        LLMCouncilArtifactInput(
            persona_artifact=_ready_persona_artifact(),
            rounds=[_round(["ref-1"])],
            evidence_refs=[_evidence_ref()],
            expected_layer_ids=["L1_market_sizing"],
            requires_plateau=True,
            plateau_converged=False,
        )
    )
    payload = _payload(artifact)

    assert artifact["status"] == "blocked"
    assert payload["downstream_consumability"]["final_report_ready"] is False
    assert "plateau_not_converged" in payload["downstream_consumability"]["reasons"]
    assert "blocked_council_plateau_not_converged" in {
        blocker["code"] for blocker in artifact["blockers"]
    }


def test_council_contract_exposed_and_fixture_agnostic():
    contract = llm_council_stage_artifact_contract_report()
    report = terminal_mod.json_contracts_report()

    assert contract["contract"] == "llm_council_stage_artifact.v1"
    assert contract["stage_id"] == "llm_council"
    assert "blocked_council_timeout_fallback_used" in contract["failure_modes"]
    assert "round_digests" in contract["required_outputs"]
    assert report["llm_council_stage_artifact_contract"] == contract

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
