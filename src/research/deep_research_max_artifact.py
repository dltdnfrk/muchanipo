"""GOALS artifact projection for Deep Research Max.

The implementation is deliberately generic: it consumes research-runtime
summaries that already exist in Muchanipo and projects them into the public
GOALS stage-artifact contract without inferring a benchmark or domain fixture
from topic text.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from src.pipeline.goals_artifacts import build_goals_stage_artifact
from src.research.autoresearch_runtime import TokenUsageLedger, runtime_contract_for_profile
from src.research.depth import depth_profile
from src.research.process_completeness import (
    REQUIRED_STEPS,
    ProcessCompletenessInput,
    ProcessCompletenessDecision,
    score_process_completeness,
)
from src.research.readiness import (
    BLOCKED,
    NEEDS_REVIEW,
    READY,
    ResearchReadinessDecision,
    ResearchReadinessInput,
    decide_research_readiness,
)


DEEP_RESEARCH_MAX_STAGE_ID = "deep_research_max"
DEEP_RESEARCH_MAX_ARTIFACT_CONTRACT = "deep_research_max_stage_artifact.v1"
DEEP_RESEARCH_MAX_RUBRIC_VERSION = "goals-loop2-deep-research-max.v1"

FAILURE_MODES: tuple[str, ...] = (
    "blocked_no_acceptable_sources",
    "blocked_provider_failure",
    "blocked_source_access",
    "blocked_fixture_overfit",
    "blocked_research_process_incomplete",
    "blocked_research_quality_needs_review",
)

CLAIM_BOUNDARY = (
    "Muchanipo exposes a local, source-backed GOALS artifact shaped by the "
    "Deep Research Max public stage contract; it does not represent or "
    "reproduce private provider internals."
)


@dataclass(frozen=True)
class DeepResearchMaxArtifactInput:
    """Inputs needed to score and serialize the public research stage."""

    brief_id: str = ""
    depth: str = "max"
    mode: str = "local"
    provider_status: str = "not_invoked"
    research_agenda: Mapping[str, Any] = field(default_factory=dict)
    query_route_ledger: Mapping[str, Any] = field(default_factory=dict)
    source_audit_summary: Mapping[str, Any] = field(default_factory=dict)
    source_decision_summary: Mapping[str, Any] = field(default_factory=dict)
    claim_evidence_summary: Mapping[str, Any] = field(default_factory=dict)
    evidence_ledger_readiness: str = ""
    evidence_ledger_metrics: Mapping[str, Any] = field(default_factory=dict)
    refutation_loop_readiness: str = ""
    refutation_loop_summary: Mapping[str, Any] = field(default_factory=dict)
    max_plus_benchmark_decision: str | None = None
    max_plus_benchmark_metrics: Mapping[str, Any] = field(default_factory=dict)
    progress_events: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    phase_trace: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    usage_ledger: Mapping[str, Any] | TokenUsageLedger | None = None
    input_refs: Sequence[Any] = field(default_factory=tuple)
    output_refs: Sequence[Any] = field(default_factory=tuple)
    evidence_refs: Sequence[Any] = field(default_factory=tuple)
    source_refs: Sequence[Any] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def readiness_input(self) -> ResearchReadinessInput:
        return ResearchReadinessInput(
            source_audit_summary=self.source_audit_summary,
            source_decision_summary=self.source_decision_summary,
            claim_evidence_summary=self.claim_evidence_summary,
            evidence_ledger_readiness=self.evidence_ledger_readiness,
            evidence_ledger_metrics=self.evidence_ledger_metrics,
            refutation_loop_readiness=self.refutation_loop_readiness,
            refutation_loop_summary=self.refutation_loop_summary,
            max_plus_benchmark_decision=self.max_plus_benchmark_decision,
            max_plus_benchmark_metrics=self.max_plus_benchmark_metrics,
        )

    def process_input(
        self,
        readiness_decision: ResearchReadinessDecision,
    ) -> ProcessCompletenessInput:
        return ProcessCompletenessInput(
            query_route_ledger=self.query_route_ledger,
            source_decision_summary=self.source_decision_summary,
            claim_evidence_summary=self.claim_evidence_summary,
            refutation_loop_summary=self.refutation_loop_summary,
            evidence_ledger_readiness=self.evidence_ledger_readiness,
            evidence_ledger_metrics=self.evidence_ledger_metrics,
            research_readiness_decision=readiness_decision.to_dict(),
            progress_events=self.progress_events,
        )


def build_deep_research_max_stage_artifact(
    artifact_input: DeepResearchMaxArtifactInput,
) -> dict[str, Any]:
    """Build the canonical GOALS artifact for the research stage."""

    profile = depth_profile(artifact_input.depth)
    runtime_contract = runtime_contract_for_profile(profile)
    readiness_decision = decide_research_readiness(artifact_input.readiness_input())
    process_decision = score_process_completeness(
        artifact_input.process_input(readiness_decision)
    )
    status = _artifact_status(
        provider_status=artifact_input.provider_status,
        readiness_decision=readiness_decision,
        process_decision=process_decision,
    )
    blocker_code = _blocker_code(
        provider_status=artifact_input.provider_status,
        readiness_decision=readiness_decision,
        process_decision=process_decision,
        source_decision_summary=artifact_input.source_decision_summary,
        max_plus_benchmark_metrics=artifact_input.max_plus_benchmark_metrics,
    )
    blockers = _blockers(
        blocker_code=blocker_code,
        readiness_decision=readiness_decision,
        process_decision=process_decision,
    )
    phase_trace = _phase_trace(artifact_input.phase_trace, runtime_contract)
    usage_ledger = _usage_ledger(artifact_input.usage_ledger)
    progress_percent = _progress_percent(status=status, process_decision=process_decision)
    metrics = _metrics(
        readiness_decision=readiness_decision,
        process_decision=process_decision,
        phase_trace=phase_trace,
        progress_event_count=len(artifact_input.progress_events),
        runtime_async_background=runtime_contract.async_background,
        profile_query_limit=profile.query_limit,
    )

    return build_goals_stage_artifact(
        DEEP_RESEARCH_MAX_STAGE_ID,
        status=status,
        inputs=_inputs(artifact_input),
        outputs=_outputs(
            artifact_input=artifact_input,
            runtime_contract=runtime_contract.to_dict(),
            readiness_decision=readiness_decision,
            process_decision=process_decision,
            phase_trace=phase_trace,
            usage_ledger=usage_ledger,
        ),
        blockers=blockers,
        gates=_gates(
            readiness_decision=readiness_decision,
            process_decision=process_decision,
        ),
        human_decision=_human_decision(
            status=status,
            blocker_code=blocker_code,
            readiness_decision=readiness_decision,
        ),
        evidence_refs=_evidence_refs(artifact_input),
        source_refs=_source_refs(artifact_input),
        metrics=metrics,
        cost={
            "usage_ledger": usage_ledger,
            "actual_usage_provided": artifact_input.usage_ledger is not None,
        },
        time={
            "target_runtime_seconds": profile.target_runtime_seconds,
            "client_timeout_seconds": runtime_contract.client_timeout_seconds,
            "stale_after_seconds": runtime_contract.stale_after_seconds,
        },
        progress_percent=progress_percent,
        legacy_subactivity={
            "legacy_stage_ids": ["targeting", "research", "evidence"],
            "subactivity": "source_backed_research_quality_gate",
            "required_steps": list(REQUIRED_STEPS),
        },
        hermes_scoring=_hermes_scoring(
            readiness_decision=readiness_decision,
            process_decision=process_decision,
            blocker_code=blocker_code,
        ),
        retry=_retry(status=status, blocker_code=blocker_code),
        failure_semantics=_failure_semantics(
            status=status,
            blocker_code=blocker_code,
            readiness_decision=readiness_decision,
            process_decision=process_decision,
        ),
        metadata={
            "specific_contract": DEEP_RESEARCH_MAX_ARTIFACT_CONTRACT,
            "claim_boundary": CLAIM_BOUNDARY,
            **dict(artifact_input.metadata),
        },
    )


def deep_research_max_stage_artifact_contract_report() -> dict[str, Any]:
    """Return the Deep Research Max stage artifact contract extension."""

    runtime_contract = runtime_contract_for_profile(depth_profile("max")).to_dict()
    return {
        "schema_version": 1,
        "contract": DEEP_RESEARCH_MAX_ARTIFACT_CONTRACT,
        "stage_id": DEEP_RESEARCH_MAX_STAGE_ID,
        "builder": "build_deep_research_max_stage_artifact",
        "claim_boundary": CLAIM_BOUNDARY,
        "required_inputs": [
            "research_agenda",
            "query_route_ledger",
            "source_decision_summary",
            "claim_evidence_summary",
            "evidence_ledger_readiness",
            "evidence_ledger_metrics",
            "refutation_loop_summary",
            "progress_events",
        ],
        "required_outputs": [
            "query_route_ledger",
            "source_decision_ledger",
            "claim_evidence_matrix",
            "evidence_ledger",
            "refutation_loop",
            "research_readiness_decision",
            "research_process_completeness",
            "runtime_contract",
            "phase_trace",
            "usage_ledger",
        ],
        "gates": [
            "research_readiness",
            "research_process_completeness",
            "hitl_plan_gate",
        ],
        "failure_modes": list(FAILURE_MODES),
        "scoring": {
            "rubric_version": DEEP_RESEARCH_MAX_RUBRIC_VERSION,
            "score_range": [0.0, 5.0],
            "readiness_values": [READY, NEEDS_REVIEW, BLOCKED],
            "blocking_missing_steps": [
                "query_route_ledger",
                "source_decision_ledger",
                "evidence_ledger",
                "research_readiness_decision",
            ],
        },
        "runtime_contract": runtime_contract,
        "fixture_isolation": {
            "topic_inference": "forbidden",
            "benchmark_fixture_coupling": "reported_only_from_explicit_metrics",
        },
        "compatibility": (
            "This extends the generic GOALS stage artifact contract with "
            "Deep Research Max scoring evidence while preserving the canonical "
            "stage id and legacy subactivity metadata."
        ),
    }


def _artifact_status(
    *,
    provider_status: str,
    readiness_decision: ResearchReadinessDecision,
    process_decision: ProcessCompletenessDecision,
) -> str:
    if _normalized(provider_status) in {"failed", "error", "provider_failure"}:
        return "blocked"
    if process_decision.readiness != "complete":
        return "blocked"
    if readiness_decision.readiness == READY:
        return "completed"
    return "blocked"


def _blocker_code(
    *,
    provider_status: str,
    readiness_decision: ResearchReadinessDecision,
    process_decision: ProcessCompletenessDecision,
    source_decision_summary: Mapping[str, Any],
    max_plus_benchmark_metrics: Mapping[str, Any],
) -> str:
    if _normalized(provider_status) in {"failed", "error", "provider_failure"}:
        return "blocked_provider_failure"
    if _truthy(max_plus_benchmark_metrics.get("fixture_coupling_detected")):
        return "blocked_fixture_overfit"
    if _number(source_decision_summary.get("source_access_blocked_count")) > 0:
        return "blocked_source_access"
    if process_decision.readiness != "complete":
        return "blocked_research_process_incomplete"
    if _number(source_decision_summary.get("accepted_count")) <= 0:
        return "blocked_no_acceptable_sources"
    if readiness_decision.readiness in {NEEDS_REVIEW, BLOCKED}:
        return "blocked_research_quality_needs_review"
    return ""


def _blockers(
    *,
    blocker_code: str,
    readiness_decision: ResearchReadinessDecision,
    process_decision: ProcessCompletenessDecision,
) -> list[dict[str, Any]]:
    if not blocker_code:
        return []
    return [
        {
            "code": blocker_code,
            "message": _blocker_message(blocker_code),
            "severity": "blocker",
            "recoverable": blocker_code
            in {
                "blocked_no_acceptable_sources",
                "blocked_source_access",
                "blocked_research_process_incomplete",
                "blocked_research_quality_needs_review",
            },
            "required_action": _required_action(blocker_code),
            "human_decision_required": blocker_code
            in {
                "blocked_no_acceptable_sources",
                "blocked_fixture_overfit",
                "blocked_research_quality_needs_review",
            },
            "reasons": list(readiness_decision.reasons),
            "missing_steps": list(process_decision.missing_steps),
        }
    ]


def _blocker_message(blocker_code: str) -> str:
    messages = {
        "blocked_no_acceptable_sources": "Research cannot proceed without accepted material sources.",
        "blocked_provider_failure": "The research provider failed before producing required evidence.",
        "blocked_source_access": "Required source access failed or was blocked.",
        "blocked_fixture_overfit": "The run reported explicit benchmark-fixture coupling.",
        "blocked_research_process_incomplete": "Required visible research-process evidence is incomplete.",
        "blocked_research_quality_needs_review": "Research quality gates require review before downstream synthesis.",
    }
    return messages.get(blocker_code, "Research artifact is blocked.")


def _required_action(blocker_code: str) -> str:
    actions = {
        "blocked_no_acceptable_sources": "collect_and_accept_material_sources",
        "blocked_provider_failure": "retry_or_switch_provider",
        "blocked_source_access": "repair_source_access_or_replace_sources",
        "blocked_fixture_overfit": "rerun_with_fixture_isolated_prompt_and_inputs",
        "blocked_research_process_incomplete": "emit_missing_research_process_artifacts",
        "blocked_research_quality_needs_review": "review_or_repair_research_quality_gates",
    }
    return actions.get(blocker_code, "repair_research_artifact")


def _human_decision(
    *,
    status: str,
    blocker_code: str,
    readiness_decision: ResearchReadinessDecision,
) -> dict[str, Any]:
    required = status == "blocked" and blocker_code in {
        "blocked_no_acceptable_sources",
        "blocked_fixture_overfit",
        "blocked_research_quality_needs_review",
    }
    return {
        "required": required,
        "status": "pending" if required else "not_required",
        "mode": "research_quality_gate" if required else "",
        "synthetic": False,
        "rationale": "; ".join(readiness_decision.reasons) if required else "",
        "required_action": _required_action(blocker_code) if required else "",
    }


def _gates(
    *,
    readiness_decision: ResearchReadinessDecision,
    process_decision: ProcessCompletenessDecision,
) -> list[dict[str, Any]]:
    return [
        {
            "gate_id": "research_readiness",
            "status": readiness_decision.readiness,
            "stop_state": readiness_decision.stop_state,
            "reasons": list(readiness_decision.reasons),
        },
        {
            "gate_id": "research_process_completeness",
            "status": process_decision.readiness,
            "score": process_decision.score,
            "missing_steps": list(process_decision.missing_steps),
        },
        {
            "gate_id": "hitl_plan_gate",
            "status": "enforced",
        },
    ]


def _inputs(artifact_input: DeepResearchMaxArtifactInput) -> list[Any]:
    inputs: list[Any] = list(artifact_input.input_refs)
    inputs.append(
        {
            "artifact_id": "research_brief",
            "brief_id": artifact_input.brief_id,
            "depth": artifact_input.depth,
            "mode": artifact_input.mode,
        }
    )
    inputs.append(
        {
            "artifact_id": "research_agenda",
            "present": bool(artifact_input.research_agenda),
            "summary": dict(artifact_input.research_agenda),
        }
    )
    return inputs


def _outputs(
    *,
    artifact_input: DeepResearchMaxArtifactInput,
    runtime_contract: Mapping[str, Any],
    readiness_decision: ResearchReadinessDecision,
    process_decision: ProcessCompletenessDecision,
    phase_trace: list[dict[str, Any]],
    usage_ledger: Mapping[str, Any],
) -> list[Any]:
    outputs: list[Any] = list(artifact_input.output_refs)
    outputs.extend(
        [
            {
                "artifact_id": "research_agenda",
                "present": bool(artifact_input.research_agenda),
                "summary": dict(artifact_input.research_agenda),
            },
            {
                "artifact_id": "query_route_ledger",
                "present": bool(artifact_input.query_route_ledger),
                "summary": dict(artifact_input.query_route_ledger),
            },
            {
                "artifact_id": "source_decision_ledger",
                "present": bool(artifact_input.source_decision_summary),
                "summary": dict(artifact_input.source_decision_summary),
            },
            {
                "artifact_id": "claim_evidence_matrix",
                "present": bool(artifact_input.claim_evidence_summary),
                "summary": dict(artifact_input.claim_evidence_summary),
            },
            {
                "artifact_id": "evidence_ledger",
                "readiness": artifact_input.evidence_ledger_readiness,
                "metrics": dict(artifact_input.evidence_ledger_metrics),
            },
            {
                "artifact_id": "refutation_loop",
                "readiness": artifact_input.refutation_loop_readiness,
                "summary": dict(artifact_input.refutation_loop_summary),
            },
            {
                "artifact_id": "research_readiness_decision",
                "payload": readiness_decision.to_dict(),
            },
            {
                "artifact_id": "research_process_completeness",
                "payload": process_decision.to_dict(),
            },
            {
                "artifact_id": "runtime_contract",
                "payload": dict(runtime_contract),
            },
            {
                "artifact_id": "phase_trace",
                "trace_kind": "observed" if artifact_input.phase_trace else "contract_template",
                "items": phase_trace,
            },
            {
                "artifact_id": "usage_ledger",
                "payload": dict(usage_ledger),
            },
        ]
    )
    return outputs


def _metrics(
    *,
    readiness_decision: ResearchReadinessDecision,
    process_decision: ProcessCompletenessDecision,
    phase_trace: Sequence[Mapping[str, Any]],
    progress_event_count: int,
    runtime_async_background: bool,
    profile_query_limit: int,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "readiness": readiness_decision.readiness,
        "stop_state": readiness_decision.stop_state,
        "process_completeness_score": process_decision.score,
        "process_completeness_readiness": process_decision.readiness,
        "process_missing_step_count": len(process_decision.missing_steps),
        "phase_trace_count": len(phase_trace),
        "progress_event_count": progress_event_count,
        "runtime_async_background": runtime_async_background,
        "profile_query_limit": profile_query_limit,
    }
    metrics.update(readiness_decision.metrics)
    metrics.update(
        {f"process.{key}": value for key, value in process_decision.metrics.items()}
    )
    return metrics


def _hermes_scoring(
    *,
    readiness_decision: ResearchReadinessDecision,
    process_decision: ProcessCompletenessDecision,
    blocker_code: str,
) -> dict[str, Any]:
    if readiness_decision.readiness == READY:
        readiness_factor = 1.0
    elif readiness_decision.readiness == NEEDS_REVIEW:
        readiness_factor = 0.5
    else:
        readiness_factor = 0.0
    score = round(5.0 * min(process_decision.score, readiness_factor), 2)
    issues = list(readiness_decision.reasons)
    issues.extend(f"missing_step:{step}" for step in process_decision.missing_steps)
    if blocker_code:
        issues.append(blocker_code)
    return {
        "score": score,
        "readiness": readiness_decision.readiness,
        "confidence": round(
            min(1.0, process_decision.score * max(readiness_factor, 0.25)),
            3,
        ),
        "rubric_version": DEEP_RESEARCH_MAX_RUBRIC_VERSION,
        "issues": issues,
    }


def _retry(*, status: str, blocker_code: str) -> dict[str, Any]:
    retryable = status == "blocked" and blocker_code != "blocked_fixture_overfit"
    return {
        "attempt": 0,
        "max_attempts": 2 if retryable else 0,
        "retryable": retryable,
        "next_action": _required_action(blocker_code) if retryable else "",
    }


def _failure_semantics(
    *,
    status: str,
    blocker_code: str,
    readiness_decision: ResearchReadinessDecision,
    process_decision: ProcessCompletenessDecision,
) -> dict[str, Any]:
    return {
        "code": blocker_code,
        "terminal": status == "failed",
        "retryable": status == "blocked" and blocker_code != "blocked_fixture_overfit",
        "stop_state": readiness_decision.stop_state,
        "process_readiness": process_decision.readiness,
        "failure_modes": list(FAILURE_MODES),
    }


def _phase_trace(
    phase_trace: Sequence[Mapping[str, Any]],
    runtime_contract: Any,
) -> list[dict[str, Any]]:
    if phase_trace:
        return [dict(item) for item in phase_trace]
    return runtime_contract.phase_trace_template()


def _usage_ledger(
    usage_ledger: Mapping[str, Any] | TokenUsageLedger | None,
) -> dict[str, int]:
    if isinstance(usage_ledger, TokenUsageLedger):
        return usage_ledger.to_dict()
    return TokenUsageLedger.from_interactions_usage(dict(usage_ledger or {})).to_dict()


def _progress_percent(
    *,
    status: str,
    process_decision: ProcessCompletenessDecision,
) -> float:
    if status == "completed":
        return 100.0
    return round(process_decision.score * 100.0, 1)


def _evidence_refs(artifact_input: DeepResearchMaxArtifactInput) -> list[Any]:
    return _refs(
        artifact_input.evidence_refs,
        artifact_input.claim_evidence_summary.get("matrix_ref"),
        artifact_input.claim_evidence_summary.get("artifact_ref"),
        artifact_input.claim_evidence_summary.get("evidence_refs"),
        artifact_input.claim_evidence_summary.get("claim_refs"),
    )


def _source_refs(artifact_input: DeepResearchMaxArtifactInput) -> list[Any]:
    return _refs(
        artifact_input.source_refs,
        artifact_input.source_decision_summary.get("ledger_ref"),
        artifact_input.source_decision_summary.get("artifact_ref"),
        artifact_input.source_decision_summary.get("source_refs"),
        artifact_input.source_decision_summary.get("accepted_source_refs"),
    )


def _refs(*values: Any) -> list[Any]:
    refs: list[Any] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, (str, bytes)):
            if value:
                refs.append(value)
            continue
        if isinstance(value, Mapping):
            refs.append(dict(value))
            continue
        try:
            refs.extend(list(value))
        except TypeError:
            refs.append(value)
    return refs


def _normalized(value: Any) -> str:
    return str(value or "").strip().lower()


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
