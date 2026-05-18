import json

import pytest

from src.interview.ontology_state import (
    OntologyExtractionArtifactInput,
    build_ontology_extraction_stage_artifact,
    ontology_extraction_stage_artifact_contract_report,
)
from src.muchanipo import terminal as terminal_mod
from src.pipeline.idea_to_council import _ontology_entities_for_persona_generation


def _source_grounded_input(**overrides):
    base = {
        "topic": "한국 65세 이상 1인 가구 재택의료 SaaS",
        "interview_turns": [
            {
                "turn_id": "turn-1",
                "question": "재택의료 SaaS에서 누가 행동하나요?",
                "answer": "65세 이상 1인 가구 사용자가 혈압 신호를 관찰하고 보호자가 승인한다.",
                "source_ref": "interview:turn-1",
            }
        ],
        "source_fragments": [
            {
                "source_ref": "source:claim-1",
                "text": "혈압 신호는 보호자 승인 workflow를 트리거한다.",
            }
        ],
        "aliases": {"재택의료 SaaS": ["home-care platform", "재택 케어 시스템"]},
        "relations": [
            {
                "source": "65세 이상 1인 가구 사용자",
                "predicate": "observes",
                "target": "혈압 신호",
                "source_refs": ["interview:turn-1"],
                "confidence": 0.72,
            }
        ],
    }
    base.update(overrides)
    return OntologyExtractionArtifactInput(**base)


def _output_by_id(artifact, artifact_id):
    for item in artifact["outputs"]:
        if item.get("artifact_id") == artifact_id:
            return item
    raise AssertionError(f"missing output artifact {artifact_id}")


def test_source_grounded_ontology_artifact_exposes_entities_relations_aliases_and_rejections():
    artifact = build_ontology_extraction_stage_artifact(
        _source_grounded_input(
            rejected_extractions=[
                {
                    "raw": "전국 모든 병원을 즉시 연동",
                    "reason": "not supported by any provided source",
                    "source_ref": "llm:candidate-2",
                }
            ]
        )
    )

    assert artifact["stage_id"] == "ontology_extraction"
    assert artifact["status"] == "completed"
    assert artifact["metadata"]["specific_contract"] == "ontology_extraction_stage_artifact.v1"
    assert artifact["progress_percent"] == 100.0
    assert artifact["hermes_scoring"]["readiness"] == "ready"
    assert artifact["metrics"]["entity_count"] >= 3
    assert artifact["metrics"]["relation_count"] >= 1
    assert artifact["metrics"]["needs_review_entity_count"] == 0
    assert artifact["metrics"]["rejected_extraction_count"] == 1

    payload = _output_by_id(artifact, "ontology_extraction")["payload"]
    assert payload["schema_version"] == 1
    assert payload["artifact_id"] == "ontology_extraction"
    assert payload["consumable"] is True
    assert payload["nodes"] == payload["entities"]
    assert payload["edges"] == payload["relations"]
    assert payload["downstream_consumability"]["persona_generation_ready"] is True
    assert payload["downstream_consumability"]["llm_council_ready"] is True
    assert payload["consumability"]["downstream_must_use_artifact"] is True
    assert payload["rejected_extractions"][0]["reason"] == "not supported by any provided source"

    entity = next(item for item in payload["entities"] if item["label"] == "재택의료 SaaS")
    assert entity["normalized_id"].startswith("entity:")
    assert entity["node_id"] == entity["normalized_id"]
    assert entity["aliases"] == ["home-care platform", "재택 케어 시스템"]
    assert entity["source_refs"]
    assert entity["evidence_refs"]
    assert entity["support_status"] == "supported"
    assert entity["status"] == "supported"
    assert 0 <= entity["uncertainty"] < 1

    relation = payload["relations"][0]
    assert relation["source_id"].startswith("entity:")
    assert relation["target_id"].startswith("entity:")
    assert relation["edge_id"].startswith("relation:")
    assert relation["predicate"] in payload["relation_vocabulary"]
    assert relation["domain_predicate"] == "observes"
    assert relation["support_status"] == "supported"
    assert relation["polarity"] == "supports"
    assert relation["source_refs"] == ["interview:turn-1"]


def test_unsupported_entity_sets_needs_review_and_blocks_consumability():
    artifact = build_ontology_extraction_stage_artifact(
        _source_grounded_input(
            source_fragments=[],
            manual_entities=[
                {
                    "label": "비급여 보험사 제휴",
                    "kind": "organization",
                    "source_refs": [],
                    "confidence": 0.4,
                }
            ],
        )
    )

    payload = _output_by_id(artifact, "ontology_extraction")["payload"]

    assert artifact["status"] == "blocked"
    assert artifact["human_decision"]["required"] is True
    assert artifact["human_decision"]["status"] == "pending"
    assert artifact["blockers"][0]["code"] == "unsupported_entities_need_review"
    assert payload["consumable"] is False
    assert "비급여 보험사 제휴" in payload["needs_review_entity_labels"]
    assert any(item["status"] == "needs_review" for item in payload["entities"])
    with pytest.raises(ValueError, match="not consumable"):
        _ontology_entities_for_persona_generation(payload, topic="fallback topic")


def test_topic_anchor_only_extraction_is_rejected_and_blocks_downstream_consumability():
    artifact = build_ontology_extraction_stage_artifact(
        OntologyExtractionArtifactInput(topic="분산 치료 경로 자동화")
    )
    payload = _output_by_id(artifact, "ontology_extraction")["payload"]

    assert artifact["status"] == "blocked"
    assert artifact["blockers"][0]["code"] == "blocked_ontology_too_sparse"
    assert payload["consumable"] is False
    assert payload["consumability"]["has_non_topic_source_grounding"] is False
    assert payload["consumability"]["downstream_must_use_artifact"] is False
    assert payload["downstream_consumability"]["persona_generation_ready"] is False
    assert payload["downstream_consumability"]["llm_council_ready"] is False
    assert any(
        gap["support_status"] == "topic_anchor_only"
        and gap["blocker_code"] == "blocked_ontology_too_sparse"
        for gap in payload["gap_records"]
        if gap.get("entity_id")
    )
    assert any(
        item["reason"] == "topic_anchor_only_not_source_grounded"
        for item in payload["rejected_extractions"]
    )
    with pytest.raises(ValueError, match="not consumable"):
        _ontology_entities_for_persona_generation(payload, topic="fallback topic")


def test_downstream_must_use_artifact_is_derived_from_canonical_payload_shape():
    artifact = build_ontology_extraction_stage_artifact(OntologyExtractionArtifactInput(topic=""))
    payload = _output_by_id(artifact, "ontology_extraction")["payload"]

    assert artifact["status"] == "blocked"
    assert payload["entities"] == []
    assert payload["consumability"]["downstream_must_use_artifact"] is False


def test_downstream_persona_generation_consumes_canonical_artifact_not_topic_rebuild():
    artifact = build_ontology_extraction_stage_artifact(_source_grounded_input())
    payload = _output_by_id(artifact, "ontology_extraction")["payload"]

    entities = _ontology_entities_for_persona_generation(payload, topic="unrelated fallback topic")

    assert entities
    assert {item["name"] for item in entities} >= {"재택의료 SaaS", "65세 이상 1인 가구 사용자"}
    assert all(item["source"] == "ontology_extraction_artifact" for item in entities)
    assert "unrelated fallback topic" not in json.dumps(entities, ensure_ascii=False)


def test_contract_report_is_exposed_from_cli_contracts_json_and_has_no_fixture_terms():
    contract = ontology_extraction_stage_artifact_contract_report()
    report = terminal_mod.json_contracts_report()

    assert contract["contract"] == "ontology_extraction_stage_artifact.v1"
    assert contract["stage_id"] == "ontology_extraction"
    assert "source_grounded_entities" in contract["required_outputs"]
    assert "downstream_consumability" in contract["required_outputs"]
    assert "supports" in contract["relation_vocabulary"]
    assert "llm_council" in contract["downstream_consumers"]
    assert "unsupported_entities_need_review" in contract["failure_modes"]
    assert "blocked_ontology_too_sparse" in contract["failure_modes"]
    assert report["ontology_extraction_stage_artifact_contract"] == contract

    payload = json.dumps(contract, ensure_ascii=False).lower()
    for forbidden in ("strawberry", "딸기", "erwinia", "fire blight"):
        assert forbidden not in payload
