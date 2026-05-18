"""Canonical GOALS artifact projection for the LLM council stage."""
from __future__ import annotations

from dataclasses import dataclass, field, is_dataclass, asdict
from typing import Any, Mapping, Sequence

from src.council.parsers import RoundResult
from src.pipeline.goals_artifacts import build_goals_stage_artifact
from src.pipeline.persona_artifact import persona_payload_from_stage_artifact


LLM_COUNCIL_STAGE_ID = "llm_council"
LLM_COUNCIL_ARTIFACT_CONTRACT = "llm_council_stage_artifact.v1"
LLM_COUNCIL_RUBRIC_VERSION = "goals-loop2-llm-council.v1"

LLM_COUNCIL_FAILURE_MODES: tuple[str, ...] = (
    "blocked_council_persona_pool_rejected",
    "blocked_council_timeout_fallback_used",
    "blocked_council_live_output_empty",
    "blocked_council_evidence_grounding_missing",
    "blocked_council_plateau_not_converged",
    "blocked_council_semantic_drift_needs_review",
)

LLM_COUNCIL_LEGACY_SUBSTEPS: tuple[str, ...] = (
    "council_trace",
    "chair_synthesis",
    "critique_to_action",
)


@dataclass(frozen=True)
class LLMCouncilArtifactInput:
    persona_artifact: Mapping[str, Any] | None
    rounds: Sequence[Any] = field(default_factory=tuple)
    turn_transcript: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    protocol_traces_by_round: Mapping[Any, Any] = field(default_factory=dict)
    progress_events: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    evidence_refs: Sequence[Any] = field(default_factory=tuple)
    expected_layer_ids: Sequence[str] = field(default_factory=tuple)
    council_session_id: str = ""
    mode: str = "offline"
    require_live: bool = False
    plateau_converged: bool | None = None
    stop_reason: str = ""
    allow_synthetic_aggregate_evidence: bool = True
    requires_plateau: bool = False
    semantic_drift_needs_review: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)


def build_llm_council_stage_artifact(
    artifact_input: LLMCouncilArtifactInput,
) -> dict[str, Any]:
    payload = build_llm_council_payload(artifact_input)
    blockers = _council_blockers(payload)
    blocker_codes = [str(blocker["code"]) for blocker in blockers]
    status = "blocked" if blockers else "completed"
    readiness = "ready" if payload["downstream_consumability"]["final_report_ready"] else "blocked"
    first_blocker = blocker_codes[0] if blocker_codes else ""

    return build_goals_stage_artifact(
        LLM_COUNCIL_STAGE_ID,
        status=status,
        inputs=[
            {
                "artifact_id": "persona_generation",
                "persona_pool_id": payload["persona_artifact_ref"].get("persona_pool_id", ""),
                "llm_council_ready": payload["persona_artifact_ref"]["llm_council_ready"],
                "present": payload["persona_artifact_ref"]["present"],
            },
            {
                "artifact_id": "council_runtime",
                "round_count": len(payload["round_digests"]),
                "expected_layer_ids": list(payload["expected_layer_ids"]),
                "require_live": payload["mode_honesty"]["require_live"],
            },
        ],
        outputs=[
            {
                "artifact_id": "llm_council",
                "contract": LLM_COUNCIL_ARTIFACT_CONTRACT,
                "present": True,
                "payload": payload,
            },
            {
                "artifact_id": "final_report_readiness",
                "present": True,
                "payload": payload["downstream_consumability"],
            },
        ],
        blockers=blockers,
        gates=[
            {
                "gate_id": "persona_pool_admission",
                "status": "passed" if payload["persona_artifact_ref"]["llm_council_ready"] else "failed",
            },
            {
                "gate_id": "round_integrity",
                "status": "passed" if not _has_reason(payload, "live_output_empty") else "failed",
                "missing_expected_layer_ids": payload["round_integrity"]["missing_expected_layer_ids"],
                "empty_live_layer_ids": payload["round_integrity"]["empty_live_layer_ids"],
            },
            {
                "gate_id": "evidence_grounding",
                "status": "passed" if not _has_reason(payload, "evidence_grounding_missing") else "failed",
                "synthetic_aggregate_round_count": len(payload["synthetic_fallback_markers"]),
                "missing_grounding_layer_ids": payload["evidence_grounding"]["missing_grounding_layer_ids"],
            },
            {
                "gate_id": "provider_runtime_honesty",
                "status": "passed" if not _has_reason(payload, "timeout_fallback_used") else "failed",
                "timeout_fallback_count": len(payload["timeout_fallback_markers"]),
            },
        ],
        human_decision={
            "required": bool(blockers),
            "status": "pending" if blockers else "not_required",
            "mode": "review_llm_council_artifact" if blockers else "",
            "rationale": "; ".join(payload["downstream_consumability"]["reasons"]),
            "required_action": _required_action(first_blocker),
        },
        evidence_refs=_artifact_evidence_refs(payload),
        source_refs=_artifact_source_refs(payload),
        metrics={
            "round_count": len(payload["round_digests"]),
            "expected_round_count": len(payload["expected_layer_ids"]),
            "direct_evidence_round_count": payload["evidence_grounding"]["direct_evidence_round_count"],
            "synthetic_aggregate_round_count": len(payload["synthetic_fallback_markers"]),
            "timeout_fallback_count": len(payload["timeout_fallback_markers"]),
            "provider_model_count": len(payload["provider_model_provenance"]),
            "final_report_ready": payload["downstream_consumability"]["final_report_ready"],
        },
        progress_percent=100.0 if not blockers else 70.0,
        legacy_subactivity={
            "legacy_stage": "council",
            "active_substeps": list(LLM_COUNCIL_LEGACY_SUBSTEPS),
        },
        hermes_scoring={
            "score": 5.0 if not blockers else 2.5,
            "readiness": readiness,
            "confidence": payload["consensus_status"]["average_confidence"],
            "rubric_version": LLM_COUNCIL_RUBRIC_VERSION,
            "issues": blocker_codes,
        },
        retry={
            "retryable": bool(blockers),
            "next_action": _required_action(first_blocker) if blockers else "start_final_report_html_yaml",
        },
        failure_semantics={
            "code": first_blocker,
            "terminal": False,
            "retryable": bool(blockers),
            "failure_modes": list(LLM_COUNCIL_FAILURE_MODES),
        },
        metadata={
            "specific_contract": LLM_COUNCIL_ARTIFACT_CONTRACT,
            "claim_boundary": (
                "LLM council readiness is derived from the consumed persona_generation "
                "artifact, structured round outputs, explicit evidence grounding, and "
                "provider/runtime honesty markers."
            ),
            **dict(artifact_input.metadata),
        },
    )


def build_llm_council_payload(
    artifact_input: LLMCouncilArtifactInput,
) -> dict[str, Any]:
    persona_payload = _persona_payload(artifact_input.persona_artifact)
    evidence_refs = [_evidence_payload(ref) for ref in artifact_input.evidence_refs]
    evidence_ids = _dedupe_strings([str(ref.get("id") or "") for ref in evidence_refs if ref.get("id")])
    expected_layer_ids = _expected_layer_ids(artifact_input, rounds=artifact_input.rounds)
    round_digests = _round_digests_payload(
        artifact_input.rounds,
        evidence_ids=evidence_ids,
        require_live=artifact_input.require_live,
        allow_synthetic_aggregate_evidence=artifact_input.allow_synthetic_aggregate_evidence,
    )
    evidence_grounding = _evidence_grounding(round_digests)
    round_integrity = _round_integrity(
        round_digests,
        expected_layer_ids=expected_layer_ids,
        require_live=artifact_input.require_live,
    )
    event_records = [dict(item) for item in artifact_input.turn_transcript]
    event_records.extend(dict(item) for item in artifact_input.progress_events)
    timeout_fallback_markers = _timeout_fallback_markers(event_records)
    provider_model_provenance = _provider_model_provenance(event_records)
    consensus_status = _consensus_status(round_digests)
    plateau_status = _plateau_status(
        artifact_input.plateau_converged,
        stop_reason=artifact_input.stop_reason,
        requires_plateau=artifact_input.requires_plateau,
    )
    semantic_drift = {
        "needs_review": bool(artifact_input.semantic_drift_needs_review),
        "source": "explicit_flag" if artifact_input.semantic_drift_needs_review else "not_detected",
    }
    downstream = _downstream_consumability(
        persona_payload=persona_payload,
        round_digests=round_digests,
        round_integrity=round_integrity,
        evidence_grounding=evidence_grounding,
        timeout_fallback_markers=timeout_fallback_markers,
        plateau_status=plateau_status,
        semantic_drift=semantic_drift,
        require_live=artifact_input.require_live,
    )

    return {
        "schema_version": 1,
        "artifact_id": "llm_council",
        "contract": LLM_COUNCIL_ARTIFACT_CONTRACT,
        "council_session_id": str(artifact_input.council_session_id or ""),
        "mode_honesty": {
            "mode": str(artifact_input.mode or ("live" if artifact_input.require_live else "offline")),
            "require_live": bool(artifact_input.require_live),
        },
        "persona_artifact_ref": _persona_artifact_ref(persona_payload),
        "expected_layer_ids": expected_layer_ids,
        "round_digests": round_digests,
        "turn_protocol_summary": _turn_protocol_summary(
            artifact_input.turn_transcript,
            artifact_input.protocol_traces_by_round,
        ),
        "consensus_status": consensus_status,
        "plateau_status": plateau_status,
        "timeout_fallback_markers": timeout_fallback_markers,
        "provider_model_provenance": provider_model_provenance,
        "evidence_refs_by_round": _evidence_refs_by_round(round_digests),
        "evidence_grounding": evidence_grounding,
        "round_integrity": round_integrity,
        "synthetic_fallback_markers": _synthetic_fallback_markers(round_digests),
        "semantic_drift": semantic_drift,
        "evidence_refs": evidence_refs,
        "downstream_consumability": downstream,
    }


def assert_council_artifact_ready_for_final_report(council_artifact: Mapping[str, Any]) -> None:
    payload = council_payload_from_stage_artifact(council_artifact)
    downstream = payload.get("downstream_consumability") or {}
    if downstream.get("final_report_ready"):
        return
    reasons = _string_list(downstream.get("reasons"))
    blocker_code = _reason_to_blocker_code(reasons[0] if reasons else "evidence_grounding_missing")
    raise ValueError(f"{blocker_code}: {', '.join(reasons)}")


def council_payload_from_stage_artifact(council_artifact: Mapping[str, Any]) -> dict[str, Any]:
    if council_artifact.get("artifact_id") == "llm_council":
        return dict(council_artifact)
    for output in council_artifact.get("outputs", []) or []:
        if isinstance(output, Mapping) and output.get("artifact_id") == "llm_council":
            payload = output.get("payload")
            if isinstance(payload, Mapping):
                return dict(payload)
    return dict(council_artifact)


def llm_council_stage_artifact_contract_report() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "contract": LLM_COUNCIL_ARTIFACT_CONTRACT,
        "stage_id": LLM_COUNCIL_STAGE_ID,
        "builder": "build_llm_council_stage_artifact",
        "failure_modes": list(LLM_COUNCIL_FAILURE_MODES),
        "legacy_substeps": list(LLM_COUNCIL_LEGACY_SUBSTEPS),
        "required_inputs": [
            "persona_generation.downstream_consumability.llm_council_ready",
            "persona_generation.admitted_personas",
            "council.rounds",
            "council.turn_transcript",
            "council.protocol_traces_by_round",
            "evidence_refs",
        ],
        "required_outputs": [
            "round_digests",
            "turn_protocol_summary",
            "consensus_status",
            "plateau_status",
            "timeout_fallback_markers",
            "provider_model_provenance",
            "evidence_refs_by_round",
            "synthetic_fallback_markers",
            "downstream_consumability.final_report_ready",
        ],
        "evidence_grounding_rule": (
            "Rounds keep direct evidence ids when provided. Aggregate evidence fallback is "
            "allowed only when explicitly marked synthetic_aggregate; live mode refuses it."
        ),
        "downstream_rule": (
            "final_report_ready is derived from persona readiness, round integrity, "
            "evidence grounding, provider/runtime honesty, plateau requirements, and "
            "semantic drift review state."
        ),
        "compatibility": (
            "Legacy council_trace, chair_synthesis, and critique_to_action substeps "
            "project to one canonical llm_council stage."
        ),
    }


def _persona_payload(persona_artifact: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(persona_artifact, Mapping):
        return {}
    return persona_payload_from_stage_artifact(persona_artifact)


def _persona_artifact_ref(persona_payload: Mapping[str, Any]) -> dict[str, Any]:
    downstream = persona_payload.get("downstream_consumability")
    if not isinstance(downstream, Mapping):
        downstream = {}
    return {
        "present": bool(persona_payload),
        "artifact_id": str(persona_payload.get("artifact_id") or ""),
        "contract": str(persona_payload.get("contract") or ""),
        "persona_pool_id": str(persona_payload.get("persona_pool_id") or ""),
        "llm_council_ready": bool(downstream.get("llm_council_ready")),
        "reasons": _string_list(downstream.get("reasons")),
        "admitted_persona_count": len(persona_payload.get("admitted_personas") or []),
    }


def _round_digests_payload(
    rounds: Sequence[Any],
    *,
    evidence_ids: Sequence[str],
    require_live: bool,
    allow_synthetic_aggregate_evidence: bool,
) -> list[dict[str, Any]]:
    digests: list[dict[str, Any]] = []
    aggregate_ids = _dedupe_strings(evidence_ids)
    for index, round_record in enumerate(rounds or [], start=1):
        record = _round_mapping(round_record)
        layer_id = str(record.get("layer_id") or record.get("layer") or f"L{index}_unknown")
        key_claim = _text(record.get("key_claim") or record.get("analysis") or record.get("consensus"))
        body_claims = _string_list(record.get("body_claims") or record.get("claims") or record.get("key_points"))
        direct_evidence_ids = _dedupe_strings(
            _string_list(record.get("evidence_ref_ids") or record.get("evidence_ids") or record.get("evidence"))
        )
        evidence_association = "direct" if direct_evidence_ids else "missing"
        evidence_ref_ids = list(direct_evidence_ids)
        aggregate_evidence_ids: list[str] = []
        synthetic_fallback = False
        if (
            not direct_evidence_ids
            and aggregate_ids
            and not require_live
            and allow_synthetic_aggregate_evidence
        ):
            evidence_association = "synthetic_aggregate"
            evidence_ref_ids = list(aggregate_ids)
            aggregate_evidence_ids = list(aggregate_ids)
            synthetic_fallback = True
        digests.append(
            {
                "round_number": index,
                "layer_id": layer_id,
                "chapter_title": str(record.get("chapter_title") or record.get("title") or ""),
                "key_claim": key_claim,
                "body_claims": body_claims,
                "confidence": _confidence(record.get("confidence_score", record.get("confidence"))),
                "framework": str(record.get("framework") or ""),
                "disagreements": _string_list(record.get("disagreements")),
                "next_actions": _string_list(record.get("next_actions") or record.get("actions")),
                "evidence_ref_ids": evidence_ref_ids,
                "direct_evidence_ref_ids": direct_evidence_ids,
                "aggregate_evidence_ref_ids": aggregate_evidence_ids,
                "evidence_association": evidence_association,
                "synthetic_fallback": synthetic_fallback,
            }
        )
    return digests


def _round_mapping(round_record: Any) -> dict[str, Any]:
    if isinstance(round_record, RoundResult):
        return {
            "layer_id": round_record.layer_id,
            "chapter_title": round_record.chapter_title,
            "key_claim": round_record.key_claim,
            "body_claims": list(round_record.body_claims),
            "evidence_ref_ids": list(round_record.evidence_ref_ids),
            "confidence_score": round_record.confidence_score,
            "framework": round_record.framework,
            "disagreements": list(round_record.disagreements),
            "next_actions": list(round_record.next_actions),
        }
    if isinstance(round_record, Mapping):
        return dict(round_record)
    if is_dataclass(round_record):
        return asdict(round_record)
    out: dict[str, Any] = {}
    for key in (
        "layer_id",
        "chapter_title",
        "key_claim",
        "body_claims",
        "evidence_ref_ids",
        "confidence_score",
        "framework",
        "disagreements",
        "next_actions",
    ):
        if hasattr(round_record, key):
            out[key] = getattr(round_record, key)
    return out


def _expected_layer_ids(artifact_input: LLMCouncilArtifactInput, *, rounds: Sequence[Any]) -> list[str]:
    explicit = _dedupe_strings([str(value) for value in artifact_input.expected_layer_ids if str(value)])
    if explicit:
        return explicit
    return _dedupe_strings([
        str(_round_mapping(round_record).get("layer_id") or "")
        for round_record in rounds or []
        if str(_round_mapping(round_record).get("layer_id") or "")
    ])


def _round_integrity(
    round_digests: Sequence[Mapping[str, Any]],
    *,
    expected_layer_ids: Sequence[str],
    require_live: bool,
) -> dict[str, Any]:
    present = {str(round_record.get("layer_id") or "") for round_record in round_digests}
    missing = [layer_id for layer_id in expected_layer_ids if layer_id not in present]
    empty_live = [
        str(round_record.get("layer_id") or "")
        for round_record in round_digests
        if require_live and not str(round_record.get("key_claim") or "").strip()
    ]
    if require_live:
        empty_live.extend(missing)
    return {
        "expected_round_count": len(expected_layer_ids),
        "observed_round_count": len(round_digests),
        "missing_expected_layer_ids": _dedupe_strings(missing),
        "empty_live_layer_ids": _dedupe_strings(empty_live),
    }


def _evidence_grounding(round_digests: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    direct = [
        str(round_record.get("layer_id") or "")
        for round_record in round_digests
        if round_record.get("evidence_association") == "direct"
    ]
    synthetic = [
        str(round_record.get("layer_id") or "")
        for round_record in round_digests
        if round_record.get("evidence_association") == "synthetic_aggregate"
    ]
    missing = [
        str(round_record.get("layer_id") or "")
        for round_record in round_digests
        if round_record.get("evidence_association") == "missing"
    ]
    return {
        "direct_evidence_round_count": len(direct),
        "synthetic_aggregate_round_count": len(synthetic),
        "missing_grounding_layer_ids": _dedupe_strings(missing),
        "direct_grounding_layer_ids": _dedupe_strings(direct),
        "synthetic_aggregate_layer_ids": _dedupe_strings(synthetic),
    }


def _downstream_consumability(
    *,
    persona_payload: Mapping[str, Any],
    round_digests: Sequence[Mapping[str, Any]],
    round_integrity: Mapping[str, Any],
    evidence_grounding: Mapping[str, Any],
    timeout_fallback_markers: Sequence[Mapping[str, Any]],
    plateau_status: Mapping[str, Any],
    semantic_drift: Mapping[str, Any],
    require_live: bool,
) -> dict[str, Any]:
    persona_ref = _persona_artifact_ref(persona_payload)
    reasons: list[str] = []
    if not persona_ref["llm_council_ready"]:
        reasons.append("persona_pool_rejected")
    if not round_digests:
        reasons.append("live_output_empty" if require_live else "evidence_grounding_missing")
    if round_integrity.get("empty_live_layer_ids"):
        reasons.append("live_output_empty")
    if any(marker.get("blocks_product_pass") for marker in timeout_fallback_markers):
        reasons.append("timeout_fallback_used")
    if evidence_grounding.get("missing_grounding_layer_ids"):
        reasons.append("evidence_grounding_missing")
    if require_live and evidence_grounding.get("synthetic_aggregate_layer_ids"):
        reasons.append("evidence_grounding_missing")
    if plateau_status.get("required") and not plateau_status.get("converged"):
        reasons.append("plateau_not_converged")
    if semantic_drift.get("needs_review"):
        reasons.append("semantic_drift_needs_review")
    reasons = _dedupe_strings(reasons)
    return {
        "final_report_ready": not reasons,
        "reasons": reasons,
        "ready_checks": {
            "persona_pool_ready": persona_ref["llm_council_ready"],
            "rounds_present": bool(round_digests),
            "live_round_integrity": not bool(round_integrity.get("empty_live_layer_ids")),
            "provider_runtime_honest": not any(marker.get("blocks_product_pass") for marker in timeout_fallback_markers),
            "evidence_grounding_ok": "evidence_grounding_missing" not in reasons,
            "plateau_ok": "plateau_not_converged" not in reasons,
            "semantic_drift_ok": "semantic_drift_needs_review" not in reasons,
        },
    }


def _turn_protocol_summary(
    turn_transcript: Sequence[Mapping[str, Any]],
    protocol_traces_by_round: Mapping[Any, Any],
) -> dict[str, Any]:
    traces = [
        trace
        for trace in (protocol_traces_by_round or {}).values()
        if isinstance(trace, Mapping)
    ]
    return {
        "turn_count": len(turn_transcript or []),
        "protocol_round_count": len(traces),
        "protocol_runtimes": _dedupe_strings(str(trace.get("runtime") or "") for trace in traces if trace.get("runtime")),
        "phase_counts": _dedupe_strings(str(trace.get("phase_count") or "") for trace in traces if trace.get("phase_count")),
        "turn_stages": _dedupe_strings(
            str(turn.get("council_stage") or turn.get("stage") or "")
            for turn in turn_transcript or []
            if str(turn.get("council_stage") or turn.get("stage") or "")
        ),
    }


def _timeout_fallback_markers(event_records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    markers: list[dict[str, Any]] = []
    for event in event_records:
        event_name = str(event.get("event") or "")
        provider = str(event.get("provider") or event.get("provider_route") or "")
        failure_kind = str(event.get("failure_kind") or "")
        is_timeout = event_name in {"council_provider_call_timeout", "council_chairman_timeout_fallback"}
        is_fallback = "fallback" in provider.lower() or event.get("blocks_product_pass") is True
        is_failure = failure_kind in {"empty_live_output", "mock_live_output", "auth_or_policy_failure"}
        if not (is_timeout or is_fallback or is_failure):
            continue
        markers.append(
            {
                "event": event_name,
                "round": event.get("round"),
                "layer_id": str(event.get("layer") or event.get("layer_id") or ""),
                "council_stage": str(event.get("council_stage") or event.get("stage") or ""),
                "provider": provider,
                "model": str(event.get("model") or event.get("retry_model") or ""),
                "failure_kind": failure_kind,
                "blocks_product_pass": bool(event.get("blocks_product_pass")),
                "retry": str(event.get("retry") or ""),
            }
        )
    return markers


def _provider_model_provenance(event_records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[tuple[str, str, str, str, str], int] = {}
    for event in event_records:
        provider = str(event.get("provider") or event.get("provider_route") or "")
        model = str(event.get("model") or event.get("retry_model") or "")
        if not provider and not model:
            continue
        key = (
            provider or "unknown",
            model or "unknown",
            str(event.get("council_stage") or event.get("stage") or ""),
            str(event.get("layer") or event.get("layer_id") or ""),
            str(event.get("retry") or ""),
        )
        counts[key] = counts.get(key, 0) + 1
    return [
        {
            "provider": provider,
            "model": model,
            "council_stage": council_stage,
            "layer_id": layer_id,
            "retry": retry,
            "call_count": call_count,
        }
        for (provider, model, council_stage, layer_id, retry), call_count in sorted(counts.items())
    ]


def _consensus_status(round_digests: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    confidences = [float(round_record.get("confidence") or 0.0) for round_record in round_digests]
    if not confidences:
        return {
            "status": "no_rounds",
            "average_confidence": 0.0,
            "min_confidence": 0.0,
            "max_confidence": 0.0,
            "disagreement_count": 0,
        }
    average = round(sum(confidences) / len(confidences), 3)
    disagreement_count = sum(len(round_record.get("disagreements") or []) for round_record in round_digests)
    if average >= 0.75 and disagreement_count == 0:
        status = "high_confidence"
    elif average >= 0.55:
        status = "emerging"
    else:
        status = "low_confidence"
    return {
        "status": status,
        "average_confidence": average,
        "min_confidence": round(min(confidences), 3),
        "max_confidence": round(max(confidences), 3),
        "disagreement_count": disagreement_count,
    }


def _plateau_status(
    plateau_converged: bool | None,
    *,
    stop_reason: str,
    requires_plateau: bool,
) -> dict[str, Any]:
    return {
        "required": bool(requires_plateau),
        "converged": bool(plateau_converged) if plateau_converged is not None else False,
        "observed": plateau_converged is not None,
        "stop_reason": str(stop_reason or ""),
    }


def _evidence_refs_by_round(round_digests: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "round_number": round_record.get("round_number"),
            "layer_id": str(round_record.get("layer_id") or ""),
            "evidence_ref_ids": _string_list(round_record.get("evidence_ref_ids")),
            "association": str(round_record.get("evidence_association") or ""),
            "synthetic_fallback": bool(round_record.get("synthetic_fallback")),
        }
        for round_record in round_digests
    ]


def _synthetic_fallback_markers(round_digests: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "type": "synthetic_aggregate_evidence",
            "round_number": round_record.get("round_number"),
            "layer_id": str(round_record.get("layer_id") or ""),
            "evidence_ref_ids": _string_list(round_record.get("aggregate_evidence_ref_ids")),
            "reason": "round_missing_direct_evidence_ids",
        }
        for round_record in round_digests
        if round_record.get("evidence_association") == "synthetic_aggregate"
    ]


def _council_blockers(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    downstream = payload.get("downstream_consumability") if isinstance(payload.get("downstream_consumability"), Mapping) else {}
    reasons = _string_list(downstream.get("reasons"))
    blockers: list[dict[str, Any]] = []
    for reason in reasons:
        code = _reason_to_blocker_code(reason)
        blockers.append(
            {
                "code": code,
                "message": _blocker_message(code),
                "severity": "blocker",
                "recoverable": True,
                "required_action": _required_action(code),
                "human_decision_required": code
                in {
                    "blocked_council_timeout_fallback_used",
                    "blocked_council_semantic_drift_needs_review",
                },
            }
        )
    return _dedupe_blockers(blockers)


def _reason_to_blocker_code(reason: str) -> str:
    mapping = {
        "persona_pool_rejected": "blocked_council_persona_pool_rejected",
        "timeout_fallback_used": "blocked_council_timeout_fallback_used",
        "live_output_empty": "blocked_council_live_output_empty",
        "evidence_grounding_missing": "blocked_council_evidence_grounding_missing",
        "plateau_not_converged": "blocked_council_plateau_not_converged",
        "semantic_drift_needs_review": "blocked_council_semantic_drift_needs_review",
    }
    return mapping.get(reason, "blocked_council_evidence_grounding_missing")


def _blocker_message(code: str) -> str:
    messages = {
        "blocked_council_persona_pool_rejected": "LLM council requires an admitted persona_generation artifact.",
        "blocked_council_timeout_fallback_used": "Council runtime used a timeout or fallback marker that blocks product pass.",
        "blocked_council_live_output_empty": "Live council output is missing or empty for a required round.",
        "blocked_council_evidence_grounding_missing": "Council rounds lack acceptable evidence grounding.",
        "blocked_council_plateau_not_converged": "Council plateau convergence was required but not observed.",
        "blocked_council_semantic_drift_needs_review": "Council semantic drift requires review before final report generation.",
    }
    return messages.get(code, "LLM council artifact is blocked.")


def _required_action(code: str) -> str:
    actions = {
        "blocked_council_persona_pool_rejected": "repair_persona_generation_admission_before_council",
        "blocked_council_timeout_fallback_used": "rerun_council_without_timeout_or_fallback_markers",
        "blocked_council_live_output_empty": "rerun_required_live_council_rounds",
        "blocked_council_evidence_grounding_missing": "attach_round_level_evidence_or_mark_aggregate_synthetic",
        "blocked_council_plateau_not_converged": "rerun_until_required_plateau_or_remove_plateau_requirement",
        "blocked_council_semantic_drift_needs_review": "review_and_resolve_council_semantic_drift",
    }
    return actions.get(code, "resolve_llm_council_blocker")


def _dedupe_blockers(blockers: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for blocker in blockers:
        code = str(blocker.get("code") or "")
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(dict(blocker))
    return out


def _artifact_evidence_refs(payload: Mapping[str, Any]) -> list[str]:
    refs: list[str] = []
    for round_record in payload.get("round_digests", []) or []:
        if isinstance(round_record, Mapping):
            refs.extend(_string_list(round_record.get("evidence_ref_ids")))
    return _dedupe_strings(refs)


def _artifact_source_refs(payload: Mapping[str, Any]) -> list[str]:
    refs: list[str] = []
    for ref in payload.get("evidence_refs", []) or []:
        if isinstance(ref, Mapping):
            refs.append(str(ref.get("source_url") or ref.get("source") or ""))
    return _dedupe_strings(refs)


def _evidence_payload(ref: Any) -> dict[str, Any]:
    if isinstance(ref, Mapping):
        return dict(ref)
    return {
        "id": str(getattr(ref, "id", "") or ""),
        "source_url": str(getattr(ref, "source_url", "") or ""),
        "source_title": str(getattr(ref, "source_title", "") or ""),
        "source_grade": str(getattr(ref, "source_grade", "") or ""),
    }


def _has_reason(payload: Mapping[str, Any], reason: str) -> bool:
    downstream = payload.get("downstream_consumability") if isinstance(payload.get("downstream_consumability"), Mapping) else {}
    return reason in _string_list(downstream.get("reasons"))


def _text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, Mapping):
        return [str(key) for key in value.keys() if str(key)]
    if isinstance(value, Sequence):
        return [str(item) for item in value if str(item)]
    return [str(value)] if str(value) else []


def _dedupe_strings(values: Sequence[str] | Any) -> list[str]:
    out: list[str] = []
    for value in values or []:
        text = str(value).strip()
        if text and text not in out:
            out.append(text)
    return out


def _confidence(value: Any) -> float:
    if isinstance(value, bool) or value is None:
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number > 1.0:
        number = number / 100.0
    return max(0.0, min(1.0, number))
