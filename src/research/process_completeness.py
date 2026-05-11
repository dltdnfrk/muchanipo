"""Backend-only visible-process completeness scoring.

The scorer consumes already-produced artifacts and progress events. It never
performs retrieval/provider calls and never infers benchmark fixture semantics
from topic text.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


REQUIRED_STEPS: tuple[str, ...] = (
    "query_route_ledger",
    "research_plan_event",
    "searching_event",
    "source_decision_ledger",
    "source_decision_event",
    "claim_evidence_matrix",
    "refutation_loop",
    "evidence_ledger",
    "research_readiness_decision",
)

_STEP_WEIGHTS: dict[str, float] = {
    "query_route_ledger": 0.12,
    "research_plan_event": 0.10,
    "searching_event": 0.10,
    "source_decision_ledger": 0.14,
    "source_decision_event": 0.10,
    "claim_evidence_matrix": 0.12,
    "refutation_loop": 0.10,
    "evidence_ledger": 0.12,
    "research_readiness_decision": 0.10,
}


@dataclass(frozen=True)
class ProcessCompletenessInput:
    query_route_ledger: Mapping[str, Any] = field(default_factory=dict)
    source_decision_summary: Mapping[str, Any] = field(default_factory=dict)
    claim_evidence_summary: Mapping[str, Any] = field(default_factory=dict)
    refutation_loop_summary: Mapping[str, Any] = field(default_factory=dict)
    evidence_ledger_readiness: str = ""
    evidence_ledger_metrics: Mapping[str, Any] = field(default_factory=dict)
    research_readiness_decision: Mapping[str, Any] = field(default_factory=dict)
    progress_events: Sequence[Mapping[str, Any]] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_route_ledger": dict(self.query_route_ledger),
            "source_decision_summary": dict(self.source_decision_summary),
            "claim_evidence_summary": dict(self.claim_evidence_summary),
            "refutation_loop_summary": dict(self.refutation_loop_summary),
            "evidence_ledger_readiness": self.evidence_ledger_readiness,
            "evidence_ledger_metrics": dict(self.evidence_ledger_metrics),
            "research_readiness_decision": dict(self.research_readiness_decision),
            "progress_event_count": len(self.progress_events),
        }


@dataclass(frozen=True)
class ProcessCompletenessDecision:
    score: float
    readiness: str
    present_steps: tuple[str, ...]
    missing_steps: tuple[str, ...]
    metrics: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "research-process-completeness.v1",
            "score": self.score,
            "readiness": self.readiness,
            "present_steps": list(self.present_steps),
            "missing_steps": list(self.missing_steps),
            "metrics": dict(self.metrics),
        }


def score_process_completeness(process_input: ProcessCompletenessInput) -> ProcessCompletenessDecision:
    """Score whether the backend exposed the research-engine sequence."""

    present: list[str] = []
    missing: list[str] = []
    statuses = _event_statuses(process_input.progress_events)

    checks = {
        "query_route_ledger": _positive_count(process_input.query_route_ledger, "route_count"),
        "research_plan_event": "research_plan_ready" in statuses,
        "searching_event": "searching" in statuses,
        "source_decision_ledger": _positive_count(process_input.source_decision_summary, "decision_count"),
        "source_decision_event": bool({"source_decision_ledger_built", "source_decision"} & statuses),
        "claim_evidence_matrix": _positive_count(process_input.claim_evidence_summary, "row_count")
        or "passed" in process_input.claim_evidence_summary,
        "refutation_loop": bool(process_input.refutation_loop_summary)
        and str(process_input.refutation_loop_summary.get("readiness") or "").strip() != "",
        "evidence_ledger": bool(str(process_input.evidence_ledger_readiness or "").strip())
        and bool(process_input.evidence_ledger_metrics),
        "research_readiness_decision": bool(str(process_input.research_readiness_decision.get("readiness") or "").strip())
        and bool(str(process_input.research_readiness_decision.get("stop_state") or "").strip()),
    }
    for step in REQUIRED_STEPS:
        (present if checks.get(step) else missing).append(step)

    score = round(sum(_STEP_WEIGHTS[step] for step in present), 3)
    if not missing:
        readiness = "complete"
    elif any(step in missing for step in ("query_route_ledger", "source_decision_ledger", "evidence_ledger", "research_readiness_decision")):
        readiness = "blocked"
    else:
        readiness = "partial"

    return ProcessCompletenessDecision(
        score=score,
        readiness=readiness,
        present_steps=tuple(present),
        missing_steps=tuple(missing),
        metrics={
            "required_step_count": len(REQUIRED_STEPS),
            "present_step_count": len(present),
            "missing_step_count": len(missing),
            "progress_event_count": len(process_input.progress_events),
            "progress_status_count": len(statuses),
            "route_count": int(_number(process_input.query_route_ledger.get("route_count"))),
            "source_decision_count": int(_number(process_input.source_decision_summary.get("decision_count"))),
        },
    )


def _event_statuses(events: Sequence[Mapping[str, Any]]) -> set[str]:
    return {str(event.get("status") or event.get("event") or "").strip() for event in events if isinstance(event, Mapping)}


def _positive_count(mapping: Mapping[str, Any], key: str) -> bool:
    return _number(mapping.get(key)) > 0


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
