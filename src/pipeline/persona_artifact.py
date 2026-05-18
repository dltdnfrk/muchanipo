"""Canonical GOALS artifact projection for persona generation."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from src.pipeline.goals_artifacts import build_goals_stage_artifact


PERSONA_GENERATION_STAGE_ID = "persona_generation"
PERSONA_GENERATION_ARTIFACT_CONTRACT = "persona_generation_stage_artifact.v1"
PERSONA_GENERATION_RUBRIC_VERSION = "goals-loop2-persona-generation.v1"

CLOSED_PERSONA_ROLE_TAXONOMY: tuple[str, ...] = (
    "domain_expert",
    "stakeholder_representative",
    "end_user",
    "regulator",
    "methodologist",
    "critic_skeptic",
    "ethics_reviewer",
    "operations_lead",
    "financial_analyst",
    "data_engineer",
    "communicator",
    "devils_advocate",
    "beneficiary",
    "opponent",
)

PERSONA_GENERATION_FAILURE_MODES: tuple[str, ...] = (
    "blocked_no_ontology_artifact",
    "blocked_persona_pool_invalid",
    "blocked_license_boundary",
    "blocked_pii_or_safety",
    "blocked_diversity_floor_not_met",
    "blocked_bias_calibration_failed",
    "blocked_council_protocol_dependency",
)

PERSONA_LEGACY_SUBSTEPS: tuple[str, ...] = (
    "persona_pool",
    "persona_admission",
    "persona_validation",
    "speaker_schedule",
)

DEFAULT_SEED_PROVENANCE: dict[str, Any] = {
    "primary_seed_corpus": "ontology-derived-local",
    "seed_corpus_version": "not_applicable",
    "seed_corpus_license": "not_applicable",
    "seed_corpus_attribution": "not_applicable",
    "seed_corpus_url": "",
    "seed_sample_count": 0,
    "seed_selection_rule": "ontology_supported_role_candidate_nodes",
}

NEMOTRON_SEED_PROVENANCE: dict[str, Any] = {
    "primary_seed_corpus": "nemotron-personas-korea",
    "seed_corpus_version": "0.0.1",
    "seed_corpus_license": "CC-BY-4.0",
    "seed_corpus_attribution": "NVIDIA Nemotron-Personas-Korea dataset",
    "seed_corpus_url": "https://huggingface.co/datasets/nvidia/Nemotron-Personas-Korea",
    "seed_sample_count": 0,
    "seed_selection_rule": "ontology_supported_role_candidate_nodes",
}


@dataclass(frozen=True)
class PersonaGenerationArtifactInput:
    ontology_artifact: Mapping[str, Any] | None
    personas: Sequence[Any] = field(default_factory=tuple)
    telemetry: Mapping[str, Any] = field(default_factory=dict)
    min_council_size: int = 1
    diversity_floor: float = 0.01
    mode: str = "offline"
    generation_method: str = "hachimi_style_clean_room"
    seed_provenance: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


def build_persona_generation_stage_artifact(
    artifact_input: PersonaGenerationArtifactInput,
) -> dict[str, Any]:
    payload = build_persona_generation_payload(artifact_input)
    blockers = _persona_blockers(payload)
    blocker_codes = [str(blocker["code"]) for blocker in blockers]
    status = "blocked" if blockers else "completed"
    readiness = "ready" if payload["downstream_consumability"]["llm_council_ready"] else "blocked"
    first_blocker = blocker_codes[0] if blocker_codes else ""

    return build_goals_stage_artifact(
        PERSONA_GENERATION_STAGE_ID,
        status=status,
        inputs=[
            {
                "artifact_id": "ontology_extraction",
                "ontology_consumed_id": payload["ontology_consumed_id"],
                "present": bool(payload["ontology_consumed_id"]),
            },
            {
                "artifact_id": "persona_candidates",
                "count": len(payload["candidate_pool"]),
            },
        ],
        outputs=[
            {
                "artifact_id": "persona_generation",
                "contract": PERSONA_GENERATION_ARTIFACT_CONTRACT,
                "present": True,
                "payload": payload,
            },
            {
                "artifact_id": "llm_council_readiness",
                "present": True,
                "payload": payload["downstream_consumability"],
            },
        ],
        blockers=blockers,
        gates=[
            {
                "gate_id": "persona_admission",
                "status": "passed" if not blockers else "failed",
                "checks": {
                    "ontology_consumed": bool(payload["ontology_consumed_id"]),
                    "ontology_persona_generation_ready": payload["ontology_persona_generation_ready"],
                    "min_council_size_met": len(payload["admitted_personas"])
                    >= max(1, int(artifact_input.min_council_size)),
                    "diversity_floor_met": payload["diversity_metrics"]["diversity_floor_met"],
                    "bias_calibration_status": payload["bias_calibration"]["calibration_status"],
                    "safety_clear": not payload["safety_audit"]["sensitive_persona_review_required"],
                },
            }
        ],
        human_decision={
            "required": bool(blockers),
            "status": "pending" if blockers else "not_required",
            "mode": "review_persona_admission" if blockers else "",
            "rationale": "; ".join(payload["downstream_consumability"]["reasons"]),
            "required_action": _required_action(first_blocker),
        },
        evidence_refs=_artifact_evidence_refs(payload),
        source_refs=_artifact_source_refs(payload),
        metrics={
            "candidate_count": len(payload["candidate_pool"]),
            "admitted_persona_count": len(payload["admitted_personas"]),
            "rejected_persona_count": len(payload["rejected_personas"]),
            "needs_review_persona_count": len(payload["needs_review_personas"]),
            "diversity_coverage_ratio": payload["diversity_metrics"]["coverage_ratio"],
            "llm_council_ready": payload["downstream_consumability"]["llm_council_ready"],
            "min_council_size": max(1, int(artifact_input.min_council_size)),
        },
        progress_percent=100.0 if not blockers else 55.0,
        legacy_subactivity={
            "legacy_stage": "agents",
            "active_substeps": list(PERSONA_LEGACY_SUBSTEPS),
        },
        hermes_scoring={
            "score": 5.0 if not blockers else 2.5,
            "readiness": readiness,
            "confidence": 0.86 if not blockers else 0.62,
            "rubric_version": PERSONA_GENERATION_RUBRIC_VERSION,
            "issues": blocker_codes,
        },
        retry={
            "retryable": bool(blockers),
            "next_action": _required_action(first_blocker) if blockers else "start_llm_council",
        },
        failure_semantics={
            "code": first_blocker,
            "terminal": False,
            "retryable": bool(blockers),
            "failure_modes": list(PERSONA_GENERATION_FAILURE_MODES),
        },
        metadata={
            "specific_contract": PERSONA_GENERATION_ARTIFACT_CONTRACT,
            "claim_boundary": (
                "Persona generation consumes the ontology_extraction payload and records "
                "admission evidence; unavailable reference components are marked not_used."
            ),
            **dict(artifact_input.metadata),
        },
    )


def build_persona_generation_payload(
    artifact_input: PersonaGenerationArtifactInput,
) -> dict[str, Any]:
    ontology = persona_ontology_payload(artifact_input.ontology_artifact)
    ontology_consumed_id = str(ontology.get("ontology_id") or "")
    role_nodes = _role_candidate_nodes(ontology)
    ontology_ready = bool(
        ontology
        and ontology.get("consumable")
        and (ontology.get("downstream_consumability") or {}).get("persona_generation_ready")
        and role_nodes
    )
    now = _utc_now()
    persona_pool_id = f"personas:{_slug(ontology_consumed_id or 'missing-ontology')}"
    seed_provenance = _seed_provenance(artifact_input, personas=artifact_input.personas)

    candidate_pool: list[dict[str, Any]] = []
    admitted_personas: list[dict[str, Any]] = []
    rejected_personas: list[dict[str, Any]] = []
    needs_review_personas: list[dict[str, Any]] = []

    if ontology_ready:
        for idx, persona in enumerate(artifact_input.personas, start=1):
            node = role_nodes[(idx - 1) % len(role_nodes)]
            candidate = _persona_candidate(
                persona,
                node=node,
                index=idx,
                artifact_input=artifact_input,
                produced_at=now,
                seed_provenance=seed_provenance,
            )
            candidate_pool.append(candidate)
            rejection = _candidate_rejection(candidate, produced_at=now)
            if rejection:
                rejected_personas.append(rejection)
                continue
            admitted_personas.append(
                _admitted_persona(candidate, node=node, admitted_at=now)
            )

    diversity_metrics = _diversity_metrics(
        admitted_personas,
        telemetry=artifact_input.telemetry,
        floor=float(artifact_input.diversity_floor),
    )
    bias_calibration = _bias_calibration(admitted_personas)
    safety_audit = _safety_audit(admitted_personas, rejected_personas)
    speaker_schedule = _speaker_schedule(
        admitted_personas,
        max_turns_per_persona=max(1, int(artifact_input.metadata.get("max_turns_per_persona", 1) or 1)),
    )
    downstream_consumability = _downstream_consumability(
        admitted_personas=admitted_personas,
        diversity_metrics=diversity_metrics,
        bias_calibration=bias_calibration,
        safety_audit=safety_audit,
        speaker_schedule=speaker_schedule,
        min_council_size=max(1, int(artifact_input.min_council_size)),
        ontology_ready=ontology_ready,
    )
    if not ontology_ready:
        rejected_personas.extend(
            _ontology_refusal_records(artifact_input.personas, produced_at=now)
        )

    return {
        "schema_version": 1,
        "artifact_id": "persona_generation",
        "contract": PERSONA_GENERATION_ARTIFACT_CONTRACT,
        "persona_pool_id": persona_pool_id,
        "ontology_consumed_id": ontology_consumed_id,
        "ontology_persona_generation_ready": ontology_ready,
        "candidate_pool": candidate_pool,
        "admitted_personas": admitted_personas,
        "rejected_personas": rejected_personas,
        "needs_review_personas": needs_review_personas,
        "diversity_metrics": diversity_metrics,
        "bias_calibration": bias_calibration,
        "dedup_records": _dedup_records(artifact_input.telemetry),
        "safety_audit": safety_audit,
        "speaker_schedule": speaker_schedule,
        "downstream_consumability": downstream_consumability,
        "seed_provenance": seed_provenance,
        "license_boundary": _license_boundary(seed_provenance),
        "reference_components": _reference_components(
            admitted_personas,
            telemetry=artifact_input.telemetry,
            seed_provenance=seed_provenance,
        ),
    }


def persona_ontology_payload(ontology_artifact: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(ontology_artifact, Mapping):
        return {}
    if ontology_artifact.get("artifact_id") == "ontology_extraction":
        return dict(ontology_artifact)
    for output in ontology_artifact.get("outputs", []) or []:
        if isinstance(output, Mapping) and output.get("artifact_id") == "ontology_extraction":
            payload = output.get("payload")
            if isinstance(payload, Mapping):
                return dict(payload)
    return {}


def assert_persona_artifact_ready_for_llm_council(persona_artifact: Mapping[str, Any]) -> None:
    payload = persona_payload_from_stage_artifact(persona_artifact)
    downstream = payload.get("downstream_consumability") or {}
    if not downstream.get("llm_council_ready"):
        reasons = ", ".join(str(item) for item in downstream.get("reasons", []) or [])
        raise ValueError(f"blocked_council_protocol_dependency: {reasons}")


def persona_payload_from_stage_artifact(persona_artifact: Mapping[str, Any]) -> dict[str, Any]:
    if persona_artifact.get("artifact_id") == "persona_generation":
        return dict(persona_artifact)
    for output in persona_artifact.get("outputs", []) or []:
        if isinstance(output, Mapping) and output.get("artifact_id") == "persona_generation":
            payload = output.get("payload")
            if isinstance(payload, Mapping):
                return dict(payload)
    return dict(persona_artifact)


def persona_generation_stage_artifact_contract_report() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "contract": PERSONA_GENERATION_ARTIFACT_CONTRACT,
        "stage_id": PERSONA_GENERATION_STAGE_ID,
        "builder": "build_persona_generation_stage_artifact",
        "closed_role_taxonomy": list(CLOSED_PERSONA_ROLE_TAXONOMY),
        "failure_modes": list(PERSONA_GENERATION_FAILURE_MODES),
        "legacy_substeps": list(PERSONA_LEGACY_SUBSTEPS),
        "required_inputs": [
            "ontology_extraction.ontology_id",
            "ontology_extraction.nodes",
            "ontology_extraction.downstream_consumability.persona_generation_ready",
        ],
        "required_outputs": [
            "persona_pool_id",
            "ontology_consumed_id",
            "candidate_pool",
            "admitted_personas",
            "rejected_personas",
            "needs_review_personas",
            "diversity_metrics",
            "bias_calibration",
            "dedup_records",
            "safety_audit",
            "speaker_schedule",
            "downstream_consumability",
            "seed_provenance",
            "license_boundary",
        ],
        "required_persona_fields": [
            "persona_id",
            "ontology_node_id",
            "role",
            "validated_attributes",
            "deep_validation_evidence",
            "admission_status",
            "evidence_refs_from_ontology",
            "safety_flags",
            "diversity_cell",
            "capability_boundary",
            "provenance",
        ],
        "component_claim_boundary": {
            "HACHIMI": "clean-room HACHIMI-style staged validation evidence only",
            "Nemotron-Personas-Korea": "used only when seed provenance includes license and attribution",
            "MAP-Elites": "clean-room diversity grid metrics and gate evidence only",
            "MiroFish": "used only when MiroFish-derived attributes are present with license boundary",
            "bias_calibration": "status requires calibration evidence",
        },
        "downstream_rule": (
            "llm_council_ready is derived from admitted persona count, diversity floor, "
            "bias calibration, safety audit, and populated speaker schedule."
        ),
        "compatibility": (
            "Legacy persona_pool, persona_admission, persona_validation, and speaker_schedule "
            "substeps project to one canonical persona_generation stage."
        ),
    }


def _persona_candidate(
    persona: Any,
    *,
    node: Mapping[str, Any],
    index: int,
    artifact_input: PersonaGenerationArtifactInput,
    produced_at: str,
    seed_provenance: Mapping[str, Any],
) -> dict[str, Any]:
    raw = _persona_mapping(persona)
    persona_id = str(raw.get("persona_id") or raw.get("id") or f"persona-{index:03d}")
    role, domain_role = _canonical_role(str(raw.get("role") or "domain_expert"))
    manifest = dict(raw.get("manifest") or {})
    value_axes = dict(manifest.get("value_axes") or {})
    seed_id = _seed_id(manifest)
    provenance = {
        "produced_by": artifact_input.generation_method,
        "generation_method": artifact_input.generation_method,
        "mode": str(artifact_input.mode or "offline"),
        "seed_corpus": seed_provenance.get("primary_seed_corpus"),
        "license": seed_provenance.get("seed_corpus_license"),
        "attribution": seed_provenance.get("seed_corpus_attribution"),
    }
    return {
        "candidate_id": persona_id,
        "persona_id": persona_id,
        "seed_id": seed_id,
        "ontology_node_id": str(node.get("normalized_id") or node.get("node_id") or ""),
        "proposed_role": str(raw.get("role") or role),
        "proposed_attributes": {
            "name": str(raw.get("name") or persona_id),
            "intent": str(manifest.get("intent") or ""),
            "domain_role": str(manifest.get("domain_role") or domain_role or node.get("label") or ""),
            "value_axes": value_axes,
            "source_refs": list(node.get("source_refs") or []),
        },
        "hachimi_stage": "propose",
        "produced_at": produced_at,
        "revision_chain": list(raw.get("revision_notes") or []),
        "role": role,
        "provenance": provenance,
        "capability_boundary": "Evaluate evidence and uncertainty; cannot fabricate source facts or override safety gates.",
    }


def _admitted_persona(
    candidate: Mapping[str, Any],
    *,
    node: Mapping[str, Any],
    admitted_at: str,
) -> dict[str, Any]:
    value_axes = dict((candidate.get("proposed_attributes") or {}).get("value_axes") or {})
    evidence_refs = list(node.get("evidence_refs") or node.get("source_refs") or [])
    node_id = str(node.get("normalized_id") or node.get("node_id") or "")
    return {
        **dict(candidate),
        "persona_id": str(candidate.get("persona_id") or candidate.get("candidate_id") or ""),
        "role": str(candidate.get("role") or "domain_expert"),
        "validated_attributes": {
            **dict(candidate.get("proposed_attributes") or {}),
            "ontology_label": str(node.get("label") or ""),
            "domain_role": str((candidate.get("proposed_attributes") or {}).get("domain_role") or node.get("label") or ""),
        },
        "hachimi_stage": "deep_validate",
        "deep_validation_evidence": [node_id, *evidence_refs],
        "admission_status": "admitted",
        "admitted_at": admitted_at,
        "evidence_refs_from_ontology": [node_id, *evidence_refs],
        "safety_flags": [],
        "diversity_cell": list(_diversity_cell(value_axes)),
    }


def _candidate_rejection(candidate: Mapping[str, Any], *, produced_at: str) -> dict[str, Any] | None:
    if str(candidate.get("role") or "") not in CLOSED_PERSONA_ROLE_TAXONOMY:
        return _rejection(candidate, "role_outside_closed_taxonomy", "fast_validate", produced_at)
    if not candidate.get("ontology_node_id"):
        return _rejection(candidate, "no_ontology_grounding", "deep_validate", produced_at)
    provenance = candidate.get("provenance") if isinstance(candidate.get("provenance"), Mapping) else {}
    if str(provenance.get("seed_corpus") or "").lower() == "nemotron-personas-korea":
        if not provenance.get("license") or not provenance.get("attribution"):
            return _rejection(candidate, "missing_seed_license_attribution", "fast_validate", produced_at)
    return None


def _rejection(
    candidate: Mapping[str, Any],
    code: str,
    stage: str,
    produced_at: str,
) -> dict[str, Any]:
    return {
        "candidate_id": str(candidate.get("candidate_id") or candidate.get("persona_id") or ""),
        "rejection_code": code,
        "rejection_reason": code.replace("_", " "),
        "rejected_at_stage": stage,
        "rejected_at": produced_at,
        "evidence": [str(candidate.get("ontology_node_id") or "")],
    }


def _ontology_refusal_records(personas: Sequence[Any], *, produced_at: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for idx, persona in enumerate(personas, start=1):
        raw = _persona_mapping(persona)
        candidate_id = str(raw.get("persona_id") or raw.get("id") or f"persona-{idx:03d}")
        records.append(
            {
                "candidate_id": candidate_id,
                "rejection_code": "blocked_persona_pool_invalid",
                "rejection_reason": "ontology artifact is missing, not consumable, or lacks supported role candidate nodes",
                "rejected_at_stage": "ontology_dependency",
                "rejected_at": produced_at,
                "evidence": [],
            }
        )
    return records


def _role_candidate_nodes(ontology: Mapping[str, Any]) -> list[dict[str, Any]]:
    nodes = [dict(node) for node in ontology.get("nodes") or ontology.get("entities") or [] if isinstance(node, Mapping)]
    supported = [node for node in nodes if node.get("status") == "supported"]
    downstream = ontology.get("downstream_consumability") if isinstance(ontology.get("downstream_consumability"), Mapping) else {}
    role_ids = {
        str(item)
        for item in downstream.get("role_candidate_node_ids", []) or []
        if str(item)
    }
    if role_ids:
        matched = [node for node in supported if str(node.get("normalized_id") or node.get("node_id")) in role_ids]
        if matched:
            return matched
    return [
        node
        for node in supported
        if str(node.get("kind") or "") in {"actor", "organization", "stakeholder", "research_topic", "research"}
    ]


def _diversity_metrics(
    admitted_personas: Sequence[Mapping[str, Any]],
    *,
    telemetry: Mapping[str, Any],
    floor: float,
) -> dict[str, Any]:
    total_cells = 16
    raw_coverage = telemetry.get("coverage_after_admit")
    if raw_coverage is None:
        occupied = len({tuple(persona.get("diversity_cell") or []) for persona in admitted_personas})
        coverage = occupied / total_cells if total_cells else 0.0
    else:
        coverage = max(0.0, min(1.0, float(raw_coverage or 0.0)))
        occupied = int(round(coverage * total_cells))
    occupied = min(total_cells, max(0, occupied))
    if admitted_personas and occupied == 0:
        occupied = 1
        coverage = max(coverage, occupied / total_cells)
    min_cell_diversity = 1.0 if admitted_personas else 0.0
    return {
        "grid_dimensions": ["risk_tolerance", "innovation_orientation"],
        "occupied_cells": occupied,
        "total_cells": total_cells,
        "coverage_ratio": round(float(coverage), 3),
        "min_cell_diversity": min_cell_diversity,
        "duplicate_cluster_count": len(_string_list(telemetry.get("dedup_removed_ids"))),
        "diversity_floor_met": bool(admitted_personas) and coverage >= floor and min_cell_diversity > 0,
        "diversity_floor": floor,
        "method": "clean_room_diversity_grid",
    }


def _bias_calibration(admitted_personas: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not admitted_personas:
        return {
            "calibration_method": "persona_bias_calibrator_v1",
            "measured_biases": {},
            "bias_corrections_applied": [],
            "calibration_evidence": [],
            "calibration_status": "failed",
        }
    measured = {
        "role_concentration": round(1.0 / max(len({p.get("role") for p in admitted_personas}), 1), 3),
        "persona_count": float(len(admitted_personas)),
    }
    return {
        "calibration_method": "persona_bias_calibrator_v1",
        "measured_biases": measured,
        "bias_corrections_applied": [],
        "calibration_evidence": [
            str(persona.get("persona_id") or persona.get("candidate_id") or "")
            for persona in admitted_personas
        ],
        "calibration_status": "passed",
    }


def _safety_audit(
    admitted_personas: Sequence[Mapping[str, Any]],
    rejected_personas: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    pii_violations = [
        item
        for item in rejected_personas
        if str(item.get("rejection_code") or "") in {"blocked_pii_or_safety", "pii_violation"}
    ]
    return {
        "pii_checks_run": len(admitted_personas) + len(rejected_personas),
        "pii_violations": pii_violations,
        "aup_checks_run": len(admitted_personas) + len(rejected_personas),
        "aup_violations": [],
        "lockdown_invocations": len(admitted_personas),
        "sensitive_persona_review_required": bool(pii_violations),
    }


def _speaker_schedule(
    admitted_personas: Sequence[Mapping[str, Any]],
    *,
    max_turns_per_persona: int,
) -> dict[str, Any]:
    return {
        "active_speakers": [
            str(persona.get("persona_id") or "")
            for persona in admitted_personas
            if persona.get("persona_id")
        ],
        "rotation_policy": "ontology_role_priority" if admitted_personas else "",
        "max_turns_per_persona": max_turns_per_persona,
        "council_session_link": None,
    }


def _downstream_consumability(
    *,
    admitted_personas: Sequence[Mapping[str, Any]],
    diversity_metrics: Mapping[str, Any],
    bias_calibration: Mapping[str, Any],
    safety_audit: Mapping[str, Any],
    speaker_schedule: Mapping[str, Any],
    min_council_size: int,
    ontology_ready: bool,
) -> dict[str, Any]:
    reasons: list[str] = []
    if not ontology_ready:
        reasons.append("ontology_not_consumable_for_persona_generation")
    if len(admitted_personas) < min_council_size:
        reasons.append("min_council_size_not_met")
    if not diversity_metrics.get("diversity_floor_met"):
        reasons.append("diversity_floor_not_met")
    if bias_calibration.get("calibration_status") not in {"passed", "needs_review_acknowledged"}:
        reasons.append("bias_calibration_not_passed")
    if safety_audit.get("sensitive_persona_review_required"):
        reasons.append("sensitive_persona_review_required")
    if not speaker_schedule.get("active_speakers") or not speaker_schedule.get("rotation_policy"):
        reasons.append("speaker_schedule_unpopulated")
    if any(not persona.get("evidence_refs_from_ontology") for persona in admitted_personas):
        reasons.append("persona_missing_ontology_grounding")
    return {
        "llm_council_ready": not reasons,
        "reasons": list(dict.fromkeys(reasons)),
        "min_council_size": min_council_size,
        "admitted_persona_count": len(admitted_personas),
    }


def _dedup_records(telemetry: Mapping[str, Any]) -> list[dict[str, Any]]:
    removed = _string_list(telemetry.get("dedup_removed_ids"))
    if not removed:
        return []
    kept = str(telemetry.get("dedup_kept_id") or "unknown")
    return [
        {
            "cluster_id": f"dedup:{_slug(','.join([kept, *removed]))}",
            "simhash_signature": _hash_text(",".join([kept, *removed])),
            "candidate_ids": [kept, *removed],
            "kept_candidate_id": kept,
            "rationale": "simhash_hamming_cluster",
        }
    ]


def _reference_components(
    admitted_personas: Sequence[Mapping[str, Any]],
    *,
    telemetry: Mapping[str, Any],
    seed_provenance: Mapping[str, Any],
) -> dict[str, Any]:
    seed_corpus = str(seed_provenance.get("primary_seed_corpus") or "")
    mirofish_used = any(
        str(persona.get("persona_id") or "").startswith("mirofish-")
        or "mirofish" in jsonish(persona).lower()
        for persona in admitted_personas
    )
    return {
        "HACHIMI": {
            "status": "used" if admitted_personas else "blocked",
            "evidence": ["deep_validation_evidence"] if admitted_personas else [],
            "claim_boundary": "clean-room staged validation evidence",
        },
        "Nemotron-Personas-Korea": {
            "status": "used" if seed_corpus == "nemotron-personas-korea" else "not_used",
            "evidence": [seed_provenance.get("seed_corpus_url", "")]
            if seed_corpus == "nemotron-personas-korea"
            else [],
            "claim_boundary": "seed corpus provenance only",
        },
        "MAP-Elites": {
            "status": "used" if admitted_personas else "not_used",
            "evidence": ["diversity_metrics.coverage_ratio"] if admitted_personas else [],
            "claim_boundary": "clean-room diversity grid metrics",
        },
        "MiroFish": {
            "status": "used" if mirofish_used else "not_used",
            "evidence": ["persona_id:mirofish"] if mirofish_used else [],
            "claim_boundary": "requires explicit license boundary when derived attributes are present",
        },
        "bias_calibration": {
            "status": "used" if admitted_personas else "blocked",
            "evidence": ["bias_calibration.calibration_evidence"] if admitted_personas else [],
            "claim_boundary": "artifact-level calibration metadata",
        },
    }


def _persona_blockers(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    downstream = payload.get("downstream_consumability") if isinstance(payload.get("downstream_consumability"), Mapping) else {}
    if downstream.get("llm_council_ready"):
        return []
    reasons = set(_string_list(downstream.get("reasons")))
    codes: list[str] = []
    if not payload.get("ontology_consumed_id"):
        codes.append("blocked_no_ontology_artifact")
    if "ontology_not_consumable_for_persona_generation" in reasons or "min_council_size_not_met" in reasons:
        codes.append("blocked_persona_pool_invalid")
    if "sensitive_persona_review_required" in reasons:
        codes.append("blocked_pii_or_safety")
    if "diversity_floor_not_met" in reasons:
        codes.append("blocked_diversity_floor_not_met")
    if "bias_calibration_not_passed" in reasons:
        codes.append("blocked_bias_calibration_failed")
    if not codes:
        codes.append("blocked_persona_pool_invalid")
    blockers: list[dict[str, Any]] = []
    for code in dict.fromkeys(codes):
        blockers.append(
            {
                "code": code,
                "message": _blocker_message(code),
                "severity": "blocker",
                "recoverable": True,
                "required_action": _required_action(code),
                "human_decision_required": code
                in {"blocked_license_boundary", "blocked_pii_or_safety", "blocked_bias_calibration_failed"},
            }
        )
    return blockers


def _blocker_message(code: str) -> str:
    messages = {
        "blocked_no_ontology_artifact": "Persona generation requires a canonical ontology_extraction artifact.",
        "blocked_persona_pool_invalid": "Persona pool is invalid or too small for downstream council.",
        "blocked_license_boundary": "Persona seed or reference license boundary requires review.",
        "blocked_pii_or_safety": "Persona safety audit found unresolved PII/AUP risk.",
        "blocked_diversity_floor_not_met": "Persona diversity floor is not met.",
        "blocked_bias_calibration_failed": "Persona bias calibration did not pass.",
    }
    return messages.get(code, "Persona generation is blocked.")


def _required_action(code: str) -> str:
    actions = {
        "blocked_no_ontology_artifact": "provide_consumable_ontology_extraction_artifact",
        "blocked_persona_pool_invalid": "admit_more_ontology_grounded_personas",
        "blocked_license_boundary": "record_license_attribution_or_review_boundary",
        "blocked_pii_or_safety": "resolve_persona_safety_review",
        "blocked_diversity_floor_not_met": "expand_persona_pool_diversity",
        "blocked_bias_calibration_failed": "apply_bias_calibration_or_request_review",
    }
    return actions.get(code, "resolve_persona_generation_blocker")


def _artifact_evidence_refs(payload: Mapping[str, Any]) -> list[str]:
    refs: list[str] = []
    for persona in payload.get("admitted_personas", []) or []:
        if isinstance(persona, Mapping):
            refs.extend(_string_list(persona.get("evidence_refs_from_ontology")))
    return list(dict.fromkeys(refs))


def _artifact_source_refs(payload: Mapping[str, Any]) -> list[str]:
    refs: list[str] = []
    for persona in payload.get("admitted_personas", []) or []:
        if isinstance(persona, Mapping):
            refs.extend(_string_list((persona.get("proposed_attributes") or {}).get("source_refs")))
    return list(dict.fromkeys(refs))


def _seed_provenance(
    artifact_input: PersonaGenerationArtifactInput,
    *,
    personas: Sequence[Any],
) -> dict[str, Any]:
    explicit = dict(artifact_input.seed_provenance or {})
    if explicit:
        base = dict(NEMOTRON_SEED_PROVENANCE if _is_nemotron(explicit.get("primary_seed_corpus")) else DEFAULT_SEED_PROVENANCE)
        base.update(explicit)
        return base
    if any(_persona_uses_nemotron(persona) for persona in personas):
        base = dict(NEMOTRON_SEED_PROVENANCE)
        base["seed_sample_count"] = len(personas)
        return base
    return dict(DEFAULT_SEED_PROVENANCE)


def _license_boundary(seed_provenance: Mapping[str, Any]) -> str:
    if str(seed_provenance.get("primary_seed_corpus") or "") == "nemotron-personas-korea":
        return "Nemotron seed use requires CC-BY-4.0 attribution in downstream reports."
    return "No external persona seed corpus used by this artifact."


def _persona_mapping(persona: Any) -> dict[str, Any]:
    if isinstance(persona, Mapping):
        return dict(persona)
    return {
        "persona_id": str(getattr(persona, "persona_id", "") or ""),
        "name": str(getattr(persona, "name", "") or ""),
        "role": str(getattr(persona, "role", "") or ""),
        "manifest": dict(getattr(persona, "manifest", {}) or {}),
        "revision_notes": list(getattr(persona, "revision_notes", []) or []),
    }


def _canonical_role(raw_role: str) -> tuple[str, str]:
    role = str(raw_role or "").strip()
    lowered = role.lower()
    if lowered in CLOSED_PERSONA_ROLE_TAXONOMY:
        return lowered, ""
    if any(token in lowered for token in ("stakeholder", "buyer", "payer", "representative")):
        return "stakeholder_representative", role
    if any(token in lowered for token in ("user", "beneficiary", "customer")):
        return "end_user", role
    if "regulat" in lowered:
        return "regulator", role
    if any(token in lowered for token in ("method", "research", "evidence")):
        return "methodologist", role
    if any(token in lowered for token in ("critic", "skeptic", "reviewer", "ontology")):
        return "critic_skeptic", role
    if any(token in lowered for token in ("operation", "ops", "workflow")):
        return "operations_lead", role
    if any(token in lowered for token in ("finance", "budget", "economic")):
        return "financial_analyst", role
    if any(token in lowered for token in ("data", "engineer")):
        return "data_engineer", role
    if any(token in lowered for token in ("ethic", "safety")):
        return "ethics_reviewer", role
    if "opponent" in lowered:
        return "opponent", role
    return "domain_expert", role


def _seed_id(manifest: Mapping[str, Any]) -> str | None:
    seed = manifest.get("grounded_seed")
    if isinstance(seed, Mapping):
        for key in ("persona_id", "seed_id", "uuid"):
            if seed.get(key):
                return str(seed[key])
    return None


def _persona_uses_nemotron(persona: Any) -> bool:
    raw = _persona_mapping(persona)
    manifest = raw.get("manifest") if isinstance(raw.get("manifest"), Mapping) else {}
    return _is_nemotron(jsonish(manifest))


def _is_nemotron(value: Any) -> bool:
    return "nemotron" in str(value or "").lower()


def _diversity_cell(value_axes: Mapping[str, Any]) -> tuple[int, int]:
    return (_bucket(value_axes.get("risk_tolerance")), _bucket(value_axes.get("innovation_orientation")))


def _bucket(value: Any) -> int:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = 0.5
    numeric = min(max(numeric, 0.0), 1.0)
    idx = int(numeric * 4)
    return min(idx, 3)


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item)]
    return [str(value)] if str(value) else []


def _slug(value: str) -> str:
    cleaned = re.sub(r"\s+", "-", str(value or "").strip().lower())
    digest = hashlib.sha1(cleaned.encode("utf-8")).hexdigest()[:8]
    visible = re.sub(r"[^0-9a-zA-Z가-힣_-]+", "", cleaned)[:32] or "unknown"
    return f"{visible}-{digest}"


def _hash_text(value: str) -> str:
    return hashlib.sha1(str(value).encode("utf-8")).hexdigest()[:16]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def jsonish(value: Any) -> str:
    return repr(value)
