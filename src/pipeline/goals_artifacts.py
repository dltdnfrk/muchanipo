"""Generic GOALS stage artifact and normalized event contract."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .goals_stages import PUBLIC_GOALS_STAGE_IDS, normalize_public_stage
from .stages import Stage


GOALS_ARTIFACT_SCHEMA_VERSION = 1
GOALS_EVENT_SCHEMA_VERSION = 1

LIFECYCLE_STATUSES: tuple[str, ...] = (
    "pending",
    "running",
    "blocked",
    "completed",
    "failed",
)

HUMAN_DECISION_STATUSES: tuple[str, ...] = (
    "not_required",
    "pending",
    "approved",
    "rejected",
    "changes_requested",
    "skipped",
)

HERMES_STAGE_STATUSES: tuple[str, ...] = (
    "not_started",
    "running",
    "done",
    "partial",
    "blocked",
    "failed",
)

HERMES_CHECK_VALUES: tuple[str, ...] = (
    "pass",
    "partial",
    "fail",
    "not_applicable",
)

GOALS_STAGE_STATUSES: tuple[str, ...] = (
    "not_started",
    "in_progress",
    "blocked",
    "completed",
    "failed",
)

GOALS_HERMES_SCORING_FIELDS: tuple[str, ...] = (
    "score",
    "readiness",
    "confidence",
    "rubric_version",
    "issues",
)

GOALS_STAGE_ARTIFACT_FIELDS: tuple[str, ...] = (
    "schema_version",
    "contract",
    "stage_id",
    "legacy_stage",
    "status",
    "inputs",
    "outputs",
    "blockers",
    "gates",
    "human_decision",
    "evidence_refs",
    "source_refs",
    "metrics",
    "cost",
    "time",
    "progress_percent",
    "legacy_subactivity",
    "hermes_scoring",
    "retry",
    "failure_semantics",
)

GOALS_STAGE_ARTIFACT_REQUIRED_KEYS: tuple[str, ...] = (
    "schema_version",
    "contract",
    "stage_id",
    "status",
    "inputs",
    "outputs",
    "blockers",
    "human_decision",
    "evidence_refs",
    "source_refs",
    "metrics",
    "legacy_subactivity",
    "hermes",
    "retry",
    "failure",
)

GOALS_STAGE_EVENT_REQUIRED_KEYS: tuple[str, ...] = (
    "schema_version",
    "contract",
    "event",
    "source_event",
    "stage_id",
    "status",
    "progress_percent",
    "artifact_ref",
    "legacy_subactivity",
    "payload",
)

_EVENT_STATUS_BY_NAME = {
    "stage_started": "running",
    "stage_completed": "completed",
    "done": "completed",
    "error": "failed",
    "stage_blocked": "blocked",
}

_STATUS_ALIASES = {
    "started": "running",
    "active": "running",
    "complete": "completed",
    "done": "completed",
    "success": "completed",
    "errored": "failed",
    "error": "failed",
    "waiting": "blocked",
    "needs_review": "blocked",
    "human_review_pending": "blocked",
}


def validate_canonical_stage_id(stage_id: str) -> str:
    if stage_id not in PUBLIC_GOALS_STAGE_IDS:
        raise ValueError(f"unknown canonical GOALS stage id: {stage_id}")
    return stage_id


def normalize_stage_id(stage: str | Stage) -> str:
    return normalize_public_stage(stage)


def normalize_lifecycle_status(
    status: str | None = None,
    *,
    source_event: str | None = None,
) -> str:
    raw = str(status or "").strip().lower()
    event_name = str(source_event or "").strip()
    if raw in LIFECYCLE_STATUSES:
        return raw
    if raw in _STATUS_ALIASES:
        return _STATUS_ALIASES[raw]
    if event_name in _EVENT_STATUS_BY_NAME:
        return _EVENT_STATUS_BY_NAME[event_name]
    if not raw:
        return "pending"
    raise ValueError(f"unknown GOALS lifecycle status: {status}")


def stage_status_for_event(event_name: str) -> str:
    event = str(event_name)
    if event in {"stage_started", "stage_progress"}:
        return "in_progress"
    if event == "stage_blocked":
        return "blocked"
    if event == "stage_completed":
        return "completed"
    if event == "stage_failed":
        return "failed"
    return "in_progress"


def _normalize_artifact_status(status: str) -> str:
    raw = str(status).strip().lower()
    aliases = {
        "pending": "not_started",
        "running": "in_progress",
        "started": "in_progress",
        "active": "in_progress",
        "done": "completed",
        "complete": "completed",
        "error": "failed",
    }
    normalized = aliases.get(raw, raw)
    if normalized not in GOALS_STAGE_STATUSES:
        raise ValueError(f"unknown GOALS stage artifact status: {status}")
    return normalized


def _validated_choice(value: str, allowed: Sequence[str], field_name: str) -> str:
    if value not in allowed:
        raise ValueError(f"unknown {field_name}: {value}")
    return value


@dataclass(frozen=True)
class GoalsStageBlocker:
    code: str
    message: str = ""
    severity: str = "blocker"
    recoverable: bool = True
    required_action: str = ""
    source_ref: str = ""
    human_decision_required: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "recoverable": self.recoverable,
            "required_action": self.required_action,
            "source_ref": self.source_ref,
            "human_decision_required": self.human_decision_required,
        }


@dataclass(frozen=True)
class GoalsHumanDecisionState:
    required: bool = False
    status: str = "not_required"
    decision_id: str = ""
    reviewer_id: str = ""
    mode: str = ""
    synthetic: bool = False
    rationale: str = ""
    required_action: str = ""

    def __post_init__(self) -> None:
        _validated_choice(self.status, HUMAN_DECISION_STATUSES, "human decision status")
        if self.required and self.status == "not_required":
            raise ValueError("required human decision cannot use status not_required")

    def as_dict(self) -> dict[str, Any]:
        return {
            "required": self.required,
            "status": self.status,
            "decision_id": self.decision_id,
            "reviewer_id": self.reviewer_id,
            "mode": self.mode,
            "synthetic": self.synthetic,
            "rationale": self.rationale,
            "required_action": self.required_action,
        }


@dataclass(frozen=True)
class GoalsStageMetrics:
    progress_percent: float = 0.0
    cost: Mapping[str, Any] = field(default_factory=dict)
    time: Mapping[str, Any] = field(default_factory=dict)
    counters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= float(self.progress_percent) <= 100.0:
            raise ValueError("progress_percent must be between 0 and 100")

    def as_dict(self) -> dict[str, Any]:
        return {
            "progress_percent": float(self.progress_percent),
            "cost": dict(self.cost),
            "time": dict(self.time),
            "counters": dict(self.counters),
        }


@dataclass(frozen=True)
class GoalsRetryState:
    attempt: int = 0
    max_attempts: int = 0
    retryable: bool = False
    retry_after_seconds: float | None = None
    next_action: str = ""

    def __post_init__(self) -> None:
        if self.attempt < 0:
            raise ValueError("retry attempt cannot be negative")
        if self.max_attempts < 0:
            raise ValueError("max retry attempts cannot be negative")

    def as_dict(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "retryable": self.retryable,
            "retry_after_seconds": self.retry_after_seconds,
            "next_action": self.next_action,
        }


@dataclass(frozen=True)
class GoalsFailureState:
    code: str = ""
    message: str = ""
    retryable: bool = False
    terminal: bool = False
    failed_at: str = ""
    source_ref: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "terminal": self.terminal,
            "failed_at": self.failed_at,
            "source_ref": self.source_ref,
        }


@dataclass(frozen=True)
class GoalsHermesScoringFields:
    status: str = "not_started"
    score_0_5: float | None = None
    evidence_paths: Sequence[str] = ()
    blockers: Sequence[str] = ()
    fixture_isolation: str = "not_applicable"
    mode_honesty: str = "not_applicable"
    human_gate_integrity: str = "not_applicable"
    claim_traceability: str = "not_applicable"
    notes: str = ""

    def __post_init__(self) -> None:
        _validated_choice(self.status, HERMES_STAGE_STATUSES, "Hermes stage status")
        for field_name in (
            "fixture_isolation",
            "mode_honesty",
            "human_gate_integrity",
            "claim_traceability",
        ):
            _validated_choice(getattr(self, field_name), HERMES_CHECK_VALUES, field_name)
        if self.score_0_5 is not None and not 0.0 <= float(self.score_0_5) <= 5.0:
            raise ValueError("score_0_5 must be between 0 and 5")

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "score_0_5": self.score_0_5,
            "evidence_paths": list(self.evidence_paths),
            "blockers": list(self.blockers),
            "fixture_isolation": self.fixture_isolation,
            "mode_honesty": self.mode_honesty,
            "human_gate_integrity": self.human_gate_integrity,
            "claim_traceability": self.claim_traceability,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class GoalsStageArtifact:
    stage_id: str
    status: str = "pending"
    inputs: Mapping[str, Any] = field(default_factory=dict)
    outputs: Mapping[str, Any] = field(default_factory=dict)
    blockers: Sequence[GoalsStageBlocker] = ()
    human_decision: GoalsHumanDecisionState = field(default_factory=GoalsHumanDecisionState)
    evidence_refs: Sequence[str] = ()
    source_refs: Sequence[str] = ()
    metrics: GoalsStageMetrics = field(default_factory=GoalsStageMetrics)
    legacy_subactivity: Mapping[str, Any] = field(default_factory=dict)
    hermes: GoalsHermesScoringFields = field(default_factory=GoalsHermesScoringFields)
    retry: GoalsRetryState = field(default_factory=GoalsRetryState)
    failure: GoalsFailureState = field(default_factory=GoalsFailureState)

    def __post_init__(self) -> None:
        validate_canonical_stage_id(self.stage_id)
        _validated_choice(self.status, LIFECYCLE_STATUSES, "lifecycle status")
        if self.status == "blocked" and not self.blockers:
            raise ValueError("blocked stage artifact must include at least one blocker")
        if self.status == "failed" and not self.failure.code:
            raise ValueError("failed stage artifact must include failure code")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": GOALS_ARTIFACT_SCHEMA_VERSION,
            "contract": "goals_stage_artifact",
            "stage_id": self.stage_id,
            "status": self.status,
            "inputs": dict(self.inputs),
            "outputs": dict(self.outputs),
            "blockers": [blocker.as_dict() for blocker in self.blockers],
            "human_decision": self.human_decision.as_dict(),
            "evidence_refs": list(self.evidence_refs),
            "source_refs": list(self.source_refs),
            "metrics": self.metrics.as_dict(),
            "legacy_subactivity": dict(self.legacy_subactivity),
            "hermes": self.hermes.as_dict(),
            "retry": self.retry.as_dict(),
            "failure": self.failure.as_dict(),
        }


@dataclass(frozen=True)
class GoalsStageEvent:
    stage_id: str
    status: str
    source_event: str = ""
    progress_percent: float = 0.0
    artifact_ref: str = ""
    legacy_subactivity: Mapping[str, Any] = field(default_factory=dict)
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_canonical_stage_id(self.stage_id)
        _validated_choice(self.status, LIFECYCLE_STATUSES, "lifecycle status")
        if not 0.0 <= float(self.progress_percent) <= 100.0:
            raise ValueError("progress_percent must be between 0 and 100")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": GOALS_EVENT_SCHEMA_VERSION,
            "contract": "goals_stage_event",
            "event": "goals_stage_event",
            "source_event": self.source_event,
            "stage_id": self.stage_id,
            "status": self.status,
            "progress_percent": float(self.progress_percent),
            "artifact_ref": self.artifact_ref,
            "legacy_subactivity": dict(self.legacy_subactivity),
            "payload": dict(self.payload),
        }


def build_stage_artifact(
    stage_id: str | Stage,
    *,
    status: str = "pending",
    inputs: Mapping[str, Any] | None = None,
    outputs: Mapping[str, Any] | None = None,
    blockers: Sequence[GoalsStageBlocker] = (),
    human_decision: GoalsHumanDecisionState | None = None,
    evidence_refs: Sequence[str] = (),
    source_refs: Sequence[str] = (),
    metrics: GoalsStageMetrics | None = None,
    legacy_subactivity: Mapping[str, Any] | None = None,
    hermes: GoalsHermesScoringFields | None = None,
    retry: GoalsRetryState | None = None,
    failure: GoalsFailureState | None = None,
) -> dict[str, Any]:
    artifact = GoalsStageArtifact(
        stage_id=normalize_stage_id(stage_id),
        status=normalize_lifecycle_status(status),
        inputs=inputs or {},
        outputs=outputs or {},
        blockers=blockers,
        human_decision=human_decision or GoalsHumanDecisionState(),
        evidence_refs=evidence_refs,
        source_refs=source_refs,
        metrics=metrics or GoalsStageMetrics(),
        legacy_subactivity=legacy_subactivity or {},
        hermes=hermes or GoalsHermesScoringFields(),
        retry=retry or GoalsRetryState(),
        failure=failure or GoalsFailureState(),
    )
    return artifact.as_dict()


def normalize_stage_event(event: Mapping[str, Any]) -> dict[str, Any]:
    source_event = str(event.get("event") or "")
    raw_stage = (
        event.get("stage_id")
        or event.get("canonical_stage_id")
        or event.get("stage")
        or event.get("pipeline_stage")
        or source_event
    )
    stage_id = normalize_stage_id(str(raw_stage))
    status = normalize_lifecycle_status(
        str(event.get("lifecycle_status") or event.get("status") or ""),
        source_event=source_event,
    )
    legacy_subactivity = _legacy_subactivity(event, raw_stage=str(raw_stage), stage_id=stage_id)
    normalized = GoalsStageEvent(
        stage_id=stage_id,
        status=status,
        source_event=source_event,
        progress_percent=_event_progress_percent(event, status=status),
        artifact_ref=str(event.get("artifact_ref") or event.get("artifact_path") or ""),
        legacy_subactivity=legacy_subactivity,
        payload=dict(event),
    )
    return normalized.as_dict()


def _legacy_subactivity(
    event: Mapping[str, Any],
    *,
    raw_stage: str,
    stage_id: str,
) -> dict[str, Any]:
    legacy_stage = raw_stage if raw_stage != stage_id else ""
    subactivity = (
        event.get("subactivity")
        or event.get("substage")
        or event.get("phase")
        or event.get("status")
        or ""
    )
    return {
        "legacy_stage": legacy_stage,
        "legacy_event": str(event.get("event") or ""),
        "subactivity": str(subactivity),
    }


def _event_progress_percent(event: Mapping[str, Any], *, status: str) -> float:
    raw = event.get("progress_percent", event.get("progress"))
    if raw is None:
        if status == "completed":
            return 100.0
        return 0.0
    value = float(raw)
    if value <= 1.0 and "progress_percent" not in event:
        value *= 100.0
    if not 0.0 <= value <= 100.0:
        raise ValueError("event progress must be between 0 and 100")
    return value


def goals_artifact_contract_report() -> dict[str, Any]:
    return {
        "schema_version": GOALS_ARTIFACT_SCHEMA_VERSION,
        "contract": "goals_stage_artifact_and_event",
        "stage_ids": list(PUBLIC_GOALS_STAGE_IDS),
        "lifecycle_statuses": list(LIFECYCLE_STATUSES),
        "human_decision_statuses": list(HUMAN_DECISION_STATUSES),
        "hermes_stage_statuses": list(HERMES_STAGE_STATUSES),
        "hermes_check_values": list(HERMES_CHECK_VALUES),
        "artifact_required_keys": list(GOALS_STAGE_ARTIFACT_REQUIRED_KEYS),
        "event_required_keys": list(GOALS_STAGE_EVENT_REQUIRED_KEYS),
        "normalization": {
            "stage_id_source_fields": [
                "stage_id",
                "canonical_stage_id",
                "stage",
                "pipeline_stage",
                "event",
            ],
            "legacy_preservation_field": "legacy_subactivity",
            "payload_preservation_field": "payload",
        },
        "compatibility": (
            "Legacy runtime stages and internal events normalize to canonical public "
            "GOALS stage ids while preserving original subactivity metadata."
        ),
    }


_DEFAULT_HERMES_SCORING: dict[str, Any] = {
    "score": None,
    "readiness": "unknown",
    "confidence": None,
    "rubric_version": None,
    "issues": [],
}


def _copy_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    return [value]


def default_hermes_scoring(**overrides: Any) -> dict[str, Any]:
    scoring = dict(_DEFAULT_HERMES_SCORING)
    for key, value in overrides.items():
        if key not in GOALS_HERMES_SCORING_FIELDS:
            raise KeyError(f"unknown Hermes scoring field: {key}")
        scoring[key] = value
    if scoring.get("issues") is None:
        scoring["issues"] = []
    elif not isinstance(scoring.get("issues"), list):
        scoring["issues"] = [scoring["issues"]]
    return scoring


def build_goals_stage_artifact(
    stage_id: str | Stage,
    *,
    status: str = "not_started",
    inputs: Sequence[Any] | None = None,
    outputs: Sequence[Any] | None = None,
    blockers: Sequence[Any] | None = None,
    gates: Sequence[Any] | None = None,
    human_decision: Mapping[str, Any] | None = None,
    evidence_refs: Sequence[Any] | None = None,
    source_refs: Sequence[Any] | None = None,
    metrics: Mapping[str, Any] | None = None,
    cost: Mapping[str, Any] | None = None,
    time: Mapping[str, Any] | None = None,
    progress_percent: float = 0.0,
    legacy_subactivity: Mapping[str, Any] | None = None,
    hermes_scoring: Mapping[str, Any] | None = None,
    retry: Mapping[str, Any] | None = None,
    failure_semantics: Mapping[str, Any] | None = None,
    legacy_stage: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    raw_stage = stage_id.value if isinstance(stage_id, Stage) else str(stage_id)
    canonical_stage_id = normalize_public_stage(raw_stage)
    status = _normalize_artifact_status(status)
    if not 0.0 <= float(progress_percent) <= 100.0:
        raise ValueError("progress_percent must be between 0 and 100")
    artifact: dict[str, Any] = {
        "schema_version": GOALS_ARTIFACT_SCHEMA_VERSION,
        "contract": "goals_stage_artifact",
        "stage_id": canonical_stage_id,
        "status": status,
        "inputs": _copy_list(inputs),
        "outputs": _copy_list(outputs),
        "blockers": _copy_list(blockers),
        "gates": _copy_list(gates),
        "human_decision": dict(human_decision or {}),
        "evidence_refs": _copy_list(evidence_refs),
        "source_refs": _copy_list(source_refs),
        "metrics": dict(metrics or {}),
        "cost": dict(cost or {}),
        "time": dict(time or {}),
        "progress_percent": float(progress_percent),
        "legacy_subactivity": dict(legacy_subactivity or {}),
        "hermes_scoring": default_hermes_scoring(**dict(hermes_scoring or {})),
        "retry": dict(retry or {}),
        "failure_semantics": dict(failure_semantics or {}),
    }
    if legacy_stage or raw_stage != canonical_stage_id:
        artifact["legacy_stage"] = legacy_stage or raw_stage
    if metadata:
        artifact["metadata"] = dict(metadata)
    return artifact


def normalize_stage_artifact(payload: Mapping[str, Any]) -> dict[str, Any]:
    stage = payload.get("stage_id") or payload.get("stage")
    if stage is None:
        raise KeyError("stage artifact requires stage_id or stage")
    return build_goals_stage_artifact(
        str(stage),
        status=str(payload.get("status") or "not_started"),
        inputs=payload.get("inputs"),
        outputs=payload.get("outputs"),
        blockers=payload.get("blockers"),
        gates=payload.get("gates"),
        human_decision=payload.get("human_decision"),
        evidence_refs=payload.get("evidence_refs"),
        source_refs=payload.get("source_refs"),
        metrics=payload.get("metrics"),
        cost=payload.get("cost"),
        time=payload.get("time"),
        progress_percent=float(payload.get("progress_percent") or 0.0),
        legacy_subactivity=payload.get("legacy_subactivity"),
        hermes_scoring=payload.get("hermes_scoring"),
        retry=payload.get("retry"),
        failure_semantics=payload.get("failure_semantics"),
        legacy_stage=payload.get("legacy_stage"),
        metadata=payload.get("metadata"),
    )


def goals_stage_artifact_contract_report() -> dict[str, Any]:
    return {
        "schema_version": GOALS_ARTIFACT_SCHEMA_VERSION,
        "contract": "goals_stage_artifacts",
        "stage_ids": list(PUBLIC_GOALS_STAGE_IDS),
        "statuses": list(GOALS_STAGE_STATUSES),
        "artifact_fields": list(GOALS_STAGE_ARTIFACT_FIELDS),
        "hermes_scoring_fields": list(GOALS_HERMES_SCORING_FIELDS),
        "per_stage": {
            stage_id: build_goals_stage_artifact(stage_id)
            for stage_id in PUBLIC_GOALS_STAGE_IDS
        },
        "legacy_contract": goals_artifact_contract_report(),
        "compatibility": (
            "Artifacts use canonical public GOALS stage ids; legacy runtime "
            "stage names remain only in compatibility metadata."
        ),
    }
