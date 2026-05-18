import json

import pytest

from src.interview.ontology_state import (
    OntologyExtractionArtifactInput,
    build_ontology_extraction_stage_artifact,
)
from src.muchanipo import terminal as terminal_mod
from src.pipeline.persona_artifact import (
    PersonaGenerationArtifactInput,
    assert_persona_artifact_ready_for_llm_council,
    build_persona_generation_stage_artifact,
    persona_generation_stage_artifact_contract_report,
)


def _output_by_id(artifact, artifact_id):
    for item in artifact["outputs"]:
        if item.get("artifact_id") == artifact_id:
            return item
    raise AssertionError(f"missing output artifact {artifact_id}")


def _ontology_payload(**overrides):
    base = {
        "topic": "지역 응급 대응 workflow",
        "interview_turns": [
            {
                "turn_id": "turn-1",
                "question": "누가 대응 workflow를 평가하나요?",
                "answer": "현장 대응 담당자가 대응 신호를 확인하고 운영 책임자가 우선순위를 조정한다.",
                "source_ref": "interview:turn-1",
            }
        ],
        "source_fragments": [
            {
                "source_ref": "source:claim-1",
                "text": "대응 신호는 운영 책임자의 의사결정을 지원한다.",
            }
        ],
        "manual_entities": [
            {
                "label": "현장 대응 담당자",
                "kind": "actor",
                "source_refs": ["interview:turn-1"],
                "confidence": 0.78,
            },
            {
                "label": "운영 책임자",
                "kind": "actor",
                "source_refs": ["interview:turn-1", "source:claim-1"],
                "confidence": 0.76,
            },
        ],
        "relations": [
            {
                "source": "현장 대응 담당자",
                "predicate": "supports",
                "target": "대응 신호",
                "source_refs": ["interview:turn-1"],
                "confidence": 0.74,
            }
        ],
    }
    base.update(overrides)
    artifact = build_ontology_extraction_stage_artifact(
        OntologyExtractionArtifactInput(**base)
    )
    return _output_by_id(artifact, "ontology_extraction")["payload"]


def _persona(persona_id="persona-001", role="stakeholder_representative"):
    return {
        "persona_id": persona_id,
        "name": "현장 대응 담당자 reviewer",
        "role": role,
        "manifest": {
            "domain_role": "현장 대응 담당자",
            "value_axes": {"risk_tolerance": 0.25, "innovation_orientation": 0.65},
            "grounded_seed": {"source": "ontology_extraction_artifact"},
        },
        "revision_notes": [
            "validated_against_ontology",
            "lockdown_checked",
            "deep_validated",
        ],
    }


def test_source_grounded_persona_artifact_exposes_admission_and_readiness():
    artifact = build_persona_generation_stage_artifact(
        PersonaGenerationArtifactInput(
            ontology_artifact=_ontology_payload(),
            personas=[_persona()],
            telemetry={"coverage_after_admit": 0.25, "dedup_removed_ids": []},
            min_council_size=1,
            mode="offline",
        )
    )

    assert artifact["stage_id"] == "persona_generation"
    assert artifact["status"] == "completed"
    assert artifact["metadata"]["specific_contract"] == "persona_generation_stage_artifact.v1"
    assert artifact["hermes_scoring"]["readiness"] == "ready"
    assert artifact["metrics"]["admitted_persona_count"] == 1

    payload = _output_by_id(artifact, "persona_generation")["payload"]
    assert payload["schema_version"] == 1
    assert payload["artifact_id"] == "persona_generation"
    assert payload["ontology_consumed_id"].startswith("ontology:")
    assert payload["downstream_consumability"]["llm_council_ready"] is True
    assert payload["bias_calibration"]["calibration_status"] == "passed"
    assert payload["bias_calibration"]["calibration_evidence"]
    assert payload["safety_audit"]["sensitive_persona_review_required"] is False
    assert payload["speaker_schedule"]["active_speakers"] == ["persona-001"]

    admitted = payload["admitted_personas"][0]
    assert admitted["persona_id"] == "persona-001"
    assert admitted["role"] == "stakeholder_representative"
    assert admitted["ontology_node_id"].startswith("entity:")
    assert admitted["evidence_refs_from_ontology"]
    assert admitted["deep_validation_evidence"]
    assert admitted["provenance"]["mode"] == "offline"
    assert admitted["provenance"]["produced_by"] == "hachimi_style_clean_room"
    assert admitted["capability_boundary"]

    components = payload["reference_components"]
    assert components["HACHIMI"]["status"] == "used"
    assert components["MAP-Elites"]["status"] == "used"
    assert components["Nemotron-Personas-Korea"]["status"] == "not_used"
    assert components["MiroFish"]["status"] == "not_used"

    assert_persona_artifact_ready_for_llm_council(payload)


def test_persona_artifact_refuses_non_consumable_ontology_and_council_dependency():
    ontology = _ontology_payload(interview_turns=[], source_fragments=[], manual_entities=[], relations=[])
    artifact = build_persona_generation_stage_artifact(
        PersonaGenerationArtifactInput(
            ontology_artifact=ontology,
            personas=[_persona()],
            min_council_size=1,
        )
    )
    payload = _output_by_id(artifact, "persona_generation")["payload"]

    assert artifact["status"] == "blocked"
    assert artifact["blockers"][0]["code"] == "blocked_persona_pool_invalid"
    assert payload["admitted_personas"] == []
    assert payload["downstream_consumability"]["llm_council_ready"] is False
    with pytest.raises(ValueError, match="blocked_council_protocol_dependency"):
        assert_persona_artifact_ready_for_llm_council(payload)


def test_persona_artifact_council_readiness_is_derived_from_minimum_pool_size():
    artifact = build_persona_generation_stage_artifact(
        PersonaGenerationArtifactInput(
            ontology_artifact=_ontology_payload(),
            personas=[_persona()],
            telemetry={"coverage_after_admit": 0.25},
            min_council_size=2,
        )
    )
    payload = _output_by_id(artifact, "persona_generation")["payload"]

    assert artifact["status"] == "blocked"
    assert artifact["blockers"][0]["code"] == "blocked_persona_pool_invalid"
    assert payload["downstream_consumability"]["llm_council_ready"] is False
    assert "min_council_size_not_met" in payload["downstream_consumability"]["reasons"]


def test_persona_generation_contract_exposed_and_fixture_agnostic():
    contract = persona_generation_stage_artifact_contract_report()
    report = terminal_mod.json_contracts_report()

    assert contract["contract"] == "persona_generation_stage_artifact.v1"
    assert contract["stage_id"] == "persona_generation"
    assert "stakeholder_representative" in contract["closed_role_taxonomy"]
    assert "blocked_persona_pool_invalid" in contract["failure_modes"]
    assert "admitted_personas" in contract["required_outputs"]
    assert report["persona_generation_stage_artifact_contract"] == contract

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
