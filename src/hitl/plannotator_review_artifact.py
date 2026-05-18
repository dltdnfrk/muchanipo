"""Canonical GOALS artifact projection for Plannotator/HITL review gates."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from src.hitl.plannotator_adapter import HITLResult
from src.muchanipo.events import normalize_goals_event
from src.pipeline.goals_artifacts import build_goals_stage_artifact


PLANNOTATOR_REVIEW_STAGE_ID = "plannotator_review"
PLANNOTATOR_REVIEW_ARTIFACT_CONTRACT = "plannotator_review_stage_artifact.v1"
PLANNOTATOR_REVIEW_RUBRIC_VERSION = "goals-loop2-plannotator-review.v1"

PLANNOTATOR_REVIEW_STATES: tuple[str, ...] = (
    "human_review_pending",
    "blocked",
    "changes_requested",
    "approved",
    "rejected",
)

PLANNOTATOR_REVIEW_FAILURE_MODES: tuple[str, ...] = (
    "blocked_human_review_required",
    "blocked_synthetic_hitl_live_mode",
    "blocked_missing_review_provenance",
    "blocked_annotation_conflict",
    "blocked_adapter_unavailable",
    "blocked_review_rejected",
)


@dataclass(frozen=True)
class PlannotatorReviewArtifactInput:
    gate_name: str
    result: HITLResult
    mode: str = ""
    live_mode: bool = False
    allow_synthetic_in_live: bool = False
    target_artifact_refs: Sequence[Any] = field(default_factory=tuple)
    applied_deltas: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    rejected_deltas: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    rubric_evolution: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    resume_token: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


def build_plannotator_review_stage_artifact(
    artifact_input: PlannotatorReviewArtifactInput,
) -> dict[str, Any]:
    """Build a durable public-stage artifact for a HITL review decision."""

    review_state = _review_state(artifact_input)
    status = _artifact_status(review_state)
    blocker_code = _blocker_code(artifact_input, review_state)
    annotation_count = len(artifact_input.result.annotations or [])
    synthetic = bool(artifact_input.result.synthetic)
    path = str(artifact_input.result.path or "")
    gate_id = str(artifact_input.result.gate_id or "")
    provenance = _decision_provenance(artifact_input)
    resumable = review_state == "changes_requested" or bool(artifact_input.result.resumable)

    return build_goals_stage_artifact(
        PLANNOTATOR_REVIEW_STAGE_ID,
        status=status,
        inputs=[
            {
                "artifact_id": "review_target",
                "gate_name": artifact_input.gate_name,
                "target_artifact_refs": list(artifact_input.target_artifact_refs),
            }
        ],
        outputs=[
            {
                "artifact_id": "review_decision",
                "review_state": review_state,
                "gate_id": gate_id,
                "session_path": path,
                "mode": artifact_input.mode,
                "synthetic": synthetic,
                "reviewer_id": artifact_input.result.reviewer_id or "",
                "decision_provenance": provenance,
            },
            {
                "artifact_id": "annotation_parse",
                "annotation_count": annotation_count,
                "annotations": list(artifact_input.result.annotations or []),
                "comments": list(artifact_input.result.comments or []),
            },
            {
                "artifact_id": "annotation_deltas",
                "applied_deltas": [dict(item) for item in artifact_input.applied_deltas],
                "rejected_deltas": [dict(item) for item in artifact_input.rejected_deltas],
                "rubric_evolution": [dict(item) for item in artifact_input.rubric_evolution],
            },
            {
                "artifact_id": "resumption",
                "resumable": resumable,
                "resume_token": artifact_input.resume_token or gate_id,
            },
        ],
        blockers=_blockers(blocker_code, review_state),
        gates=[
            {
                "gate_id": artifact_input.gate_name,
                "status": review_state,
                "synthetic": synthetic,
                "live_mode": artifact_input.live_mode,
            }
        ],
        human_decision={
            "required": review_state
            in {"human_review_pending", "changes_requested", "rejected", "blocked"},
            "status": _human_decision_status(review_state),
            "decision_id": gate_id,
            "reviewer_id": artifact_input.result.reviewer_id or "",
            "mode": artifact_input.mode,
            "synthetic": synthetic,
            "rationale": "; ".join(artifact_input.result.comments or []),
            "required_action": _required_action(blocker_code, review_state),
        },
        evidence_refs=list(artifact_input.target_artifact_refs),
        source_refs=[path] if path else [],
        metrics={
            "review_state": review_state,
            "annotation_count": annotation_count,
            "applied_delta_count": len(artifact_input.applied_deltas),
            "rejected_delta_count": len(artifact_input.rejected_deltas),
            "rubric_evolution_count": len(artifact_input.rubric_evolution),
            "synthetic": synthetic,
            "live_mode": artifact_input.live_mode,
            "resumable": resumable,
        },
        progress_percent=100.0 if review_state == "approved" else 0.0,
        legacy_subactivity={
            "legacy_stage": "hitl_gate",
            "subactivity": artifact_input.gate_name,
        },
        hermes_scoring={
            "score": _score(review_state, blocker_code),
            "readiness": review_state,
            "confidence": 1.0 if review_state == "approved" and not synthetic else 0.5,
            "rubric_version": PLANNOTATOR_REVIEW_RUBRIC_VERSION,
            "issues": [blocker_code] if blocker_code else [],
        },
        retry={
            "retryable": review_state in {"human_review_pending", "changes_requested"},
            "next_action": _required_action(blocker_code, review_state),
        },
        failure_semantics={
            "code": blocker_code,
            "terminal": review_state == "rejected",
            "retryable": review_state in {"human_review_pending", "changes_requested"},
            "failure_modes": list(PLANNOTATOR_REVIEW_FAILURE_MODES),
        },
        metadata={
            "specific_contract": PLANNOTATOR_REVIEW_ARTIFACT_CONTRACT,
            **dict(artifact_input.metadata),
        },
    )


def build_plannotator_review_stage_event(
    artifact_input: PlannotatorReviewArtifactInput,
) -> dict[str, Any]:
    """Return the normalized canonical event for a HITL review decision."""

    artifact = build_plannotator_review_stage_artifact(artifact_input)
    review_state = artifact["metrics"]["review_state"]
    event_name = {
        "approved": "stage_completed",
        "rejected": "stage_blocked",
        "changes_requested": "stage_blocked",
        "blocked": "stage_blocked",
        "human_review_pending": "stage_blocked",
    }[review_state]
    return normalize_goals_event(
        {
            "event": event_name,
            "stage": PLANNOTATOR_REVIEW_STAGE_ID,
            "status": artifact["status"],
            "review_state": review_state,
            "gate_id": artifact_input.result.gate_id or "",
            "path": artifact_input.result.path or "",
            "synthetic": artifact_input.result.synthetic,
            "annotation_count": len(artifact_input.result.annotations or []),
        }
    )


def plannotator_review_stage_artifact_contract_report() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "contract": PLANNOTATOR_REVIEW_ARTIFACT_CONTRACT,
        "stage_id": PLANNOTATOR_REVIEW_STAGE_ID,
        "builder": "build_plannotator_review_stage_artifact",
        "event_builder": "build_plannotator_review_stage_event",
        "review_states": list(PLANNOTATOR_REVIEW_STATES),
        "failure_modes": list(PLANNOTATOR_REVIEW_FAILURE_MODES),
        "required_outputs": [
            "review_decision",
            "annotation_parse",
            "annotation_deltas",
            "resumption",
        ],
        "required_decision_fields": [
            "gate_id",
            "session_path",
            "mode",
            "synthetic",
            "reviewer_id",
            "decision_provenance",
        ],
        "live_mode_rule": (
            "Synthetic review decisions are blocked in live mode unless an "
            "explicit offline/test allowance is supplied by the caller."
        ),
        "compatibility": (
            "Legacy hitl_gate events are projected to the canonical "
            "plannotator_review stage while preserving gate/session metadata."
        ),
    }


def _review_state(artifact_input: PlannotatorReviewArtifactInput) -> str:
    result = artifact_input.result
    if (
        artifact_input.live_mode
        and result.synthetic
        and not artifact_input.allow_synthetic_in_live
    ):
        return "blocked"
    if artifact_input.live_mode and result.status == "approved" and not _has_provenance(result):
        return "blocked"
    if result.status == "pending":
        return "human_review_pending"
    if result.status in {"approved", "changes_requested", "rejected"}:
        return result.status
    return "blocked"


def _artifact_status(review_state: str) -> str:
    if review_state == "approved":
        return "completed"
    return "blocked"


def _blocker_code(
    artifact_input: PlannotatorReviewArtifactInput,
    review_state: str,
) -> str:
    result = artifact_input.result
    if (
        artifact_input.live_mode
        and result.synthetic
        and not artifact_input.allow_synthetic_in_live
    ):
        return "blocked_synthetic_hitl_live_mode"
    if artifact_input.live_mode and result.status == "approved" and not _has_provenance(result):
        return "blocked_missing_review_provenance"
    if review_state == "human_review_pending":
        return "blocked_human_review_required"
    if review_state == "changes_requested":
        return "blocked_annotation_conflict"
    if review_state == "rejected":
        return "blocked_review_rejected"
    return ""


def _blockers(blocker_code: str, review_state: str) -> list[dict[str, Any]]:
    if not blocker_code:
        return []
    return [
        {
            "code": blocker_code,
            "message": _blocker_message(blocker_code),
            "severity": "blocker",
            "recoverable": review_state in {"human_review_pending", "changes_requested"},
            "required_action": _required_action(blocker_code, review_state),
            "human_decision_required": review_state
            in {"human_review_pending", "changes_requested", "rejected"},
        }
    ]


def _blocker_message(blocker_code: str) -> str:
    messages = {
        "blocked_human_review_required": "A human review decision is required.",
        "blocked_synthetic_hitl_live_mode": "Synthetic HITL approval cannot satisfy live mode.",
        "blocked_missing_review_provenance": "Approved live review is missing session/path provenance.",
        "blocked_annotation_conflict": "Reviewer requested changes that must be applied or rejected.",
        "blocked_adapter_unavailable": "Required review adapter is unavailable.",
        "blocked_review_rejected": "Reviewer rejected the gate.",
    }
    return messages.get(blocker_code, "Plannotator review is blocked.")


def _required_action(blocker_code: str, review_state: str) -> str:
    actions = {
        "blocked_human_review_required": "wait_for_human_review",
        "blocked_synthetic_hitl_live_mode": "collect_real_human_review_or_switch_to_offline_mode",
        "blocked_missing_review_provenance": "persist_review_session_path_and_decision_provenance",
        "blocked_annotation_conflict": "apply_or_reject_requested_annotation_deltas",
        "blocked_adapter_unavailable": "repair_plannotator_adapter_or_use_approved_fallback",
        "blocked_review_rejected": "revise_artifact_before_resubmission",
    }
    return actions.get(blocker_code) or (
        "continue_downstream" if review_state == "approved" else "resume_review"
    )


def _human_decision_status(review_state: str) -> str:
    if review_state == "human_review_pending":
        return "pending"
    if review_state in {"approved", "changes_requested", "rejected"}:
        return review_state
    return "pending"


def _score(review_state: str, blocker_code: str) -> float:
    if review_state == "approved" and not blocker_code:
        return 5.0
    if review_state == "changes_requested":
        return 2.5
    if review_state == "human_review_pending":
        return 1.0
    return 0.0


def _has_provenance(result: HITLResult) -> bool:
    return bool(result.gate_id and result.path)


def _decision_provenance(artifact_input: PlannotatorReviewArtifactInput) -> dict[str, Any]:
    result = artifact_input.result
    provenance = dict(result.decision_provenance or {})
    provenance.setdefault("mode", artifact_input.mode)
    provenance.setdefault("synthetic", bool(result.synthetic))
    provenance.setdefault("gate_id", result.gate_id or "")
    provenance.setdefault("path", result.path or "")
    return provenance
