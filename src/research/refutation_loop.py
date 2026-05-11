"""Deterministic backend refutation/gap loop.

The first slice is deliberately offline: it proves that the research backend
planned skepticism/gap work and records whether available source decisions are
sufficient, without pretending that a live counter-search was performed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from src.evidence.artifact import Finding
from src.report.claim_matrix import ClaimEvidenceMatrix
from src.research.source_decision_ledger import SourceDecisionLedger

_REFUTATION_INTENTS = {"refutation", "refute"}
_GAP_INTENTS = {"gap_fill", "gap", "limitations"}
_MATERIAL_ROLES = {"core_evidence", "comparison"}


@dataclass(frozen=True)
class RefutationTask:
    task_id: str
    task_type: str
    query: str
    route_id: str | None = None
    claim: str = ""
    reason: str = ""
    source_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "query": self.query,
            "route_id": self.route_id,
            "claim": self.claim,
            "reason": self.reason,
            "source_ids": list(self.source_ids),
        }


@dataclass(frozen=True)
class RefutationResult:
    task_id: str
    status: str
    decision: str
    evidence_source_ids: tuple[str, ...] = ()
    contradiction_source_ids: tuple[str, ...] = ()
    unresolved_gap_codes: tuple[str, ...] = ()
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "decision": self.decision,
            "evidence_source_ids": list(self.evidence_source_ids),
            "contradiction_source_ids": list(self.contradiction_source_ids),
            "unresolved_gap_codes": list(self.unresolved_gap_codes),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RefutationLoopReport:
    tasks: tuple[RefutationTask, ...]
    results: tuple[RefutationResult, ...]
    readiness: str
    reason: str
    contradiction_count: int = 0
    unresolved_gap_count: int = 0
    events: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def summary(self) -> dict[str, Any]:
        return {
            "task_count": len(self.tasks),
            "result_count": len(self.results),
            "readiness": self.readiness,
            "reason": self.reason,
            "contradiction_count": self.contradiction_count,
            "unresolved_gap_count": self.unresolved_gap_count,
            "unresolved_gap_codes": sorted({code for result in self.results for code in result.unresolved_gap_codes}),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary(),
            "tasks": [task.to_dict() for task in self.tasks],
            "results": [result.to_dict() for result in self.results],
            "events": list(self.events),
        }


def build_refutation_tasks(
    plan: Any,
    *,
    claim_matrix: ClaimEvidenceMatrix | None = None,
    source_decision_ledger: SourceDecisionLedger | None = None,
) -> tuple[RefutationTask, ...]:
    """Build deterministic skepticism tasks from routes and material claims."""

    tasks: list[RefutationTask] = []
    seen: set[tuple[str, str]] = set()
    for index, route in enumerate(getattr(plan, "query_routes", []) or [], start=1):
        if not isinstance(route, dict):
            continue
        intent = str(route.get("intent") or "").casefold().strip()
        if intent not in (_REFUTATION_INTENTS | _GAP_INTENTS):
            continue
        query = str(route.get("query") or "").strip()
        if not query:
            continue
        task_type = "gap" if intent in _GAP_INTENTS else "refutation"
        key = (task_type, query)
        if key in seen:
            continue
        seen.add(key)
        tasks.append(
            RefutationTask(
                task_id=f"route-{index}-{task_type}",
                task_type=task_type,
                query=query,
                route_id=str(route.get("route_id") or "") or None,
                reason=str(route.get("continue_reason") or route.get("purpose") or "planned skepticism route"),
            )
        )

    if claim_matrix is not None:
        accepted_ids = _accepted_material_source_ids(source_decision_ledger)
        for index, row in enumerate(claim_matrix.rows, start=1):
            if float(row.confidence or 0.0) < 0.75 and row.status == "unsupported":
                continue
            if row.claim in {task.claim for task in tasks if task.claim}:
                continue
            tasks.append(
                RefutationTask(
                    task_id=f"claim-{index}-refutation",
                    task_type="refutation",
                    query=f"counter evidence limitations for: {row.claim[:160]}",
                    claim=row.claim,
                    reason="high-confidence or material claim requires explicit skepticism/gap check",
                    source_ids=tuple(source_id for source_id in row.supporting_source_ids if source_id in accepted_ids),
                )
            )
    return tuple(tasks)


def run_refutation_loop(
    plan: Any,
    *,
    claim_matrix: ClaimEvidenceMatrix,
    source_decision_ledger: SourceDecisionLedger,
) -> RefutationLoopReport:
    tasks = build_refutation_tasks(
        plan,
        claim_matrix=claim_matrix,
        source_decision_ledger=source_decision_ledger,
    )
    accepted_ids = _accepted_material_source_ids(source_decision_ledger)
    results: list[RefutationResult] = []
    events: list[dict[str, Any]] = [{"status": "refutation_pass_started", "task_count": len(tasks)}]

    if not tasks:
        events.append({"status": "refutation_pass_completed", "readiness": "skipped", "reason": "no_refutation_tasks"})
        return RefutationLoopReport(tasks=(), results=(), readiness="skipped", reason="no_refutation_tasks", events=tuple(events))

    for task in tasks:
        events.append({"status": "refutation_query_planned", **task.to_dict()})
        task_source_ids = tuple(source_id for source_id in task.source_ids if source_id in accepted_ids)
        if task.claim and not task_source_ids:
            result = RefutationResult(
                task_id=task.task_id,
                status="blocked",
                decision="insufficient_sources",
                unresolved_gap_codes=("insufficient_accepted_material_sources",),
                reason="claim-level refutation check has no accepted material source-decision support",
            )
        elif source_decision_ledger.decisions and not accepted_ids:
            result = RefutationResult(
                task_id=task.task_id,
                status="blocked",
                decision="insufficient_sources",
                unresolved_gap_codes=("no_accepted_material_sources",),
                reason="source decisions exist but none are accepted material support",
            )
        else:
            evidence_ids = task_source_ids or tuple(sorted(accepted_ids))[:1]
            result = RefutationResult(
                task_id=task.task_id,
                status="completed",
                decision="no_contradiction_found",
                evidence_source_ids=evidence_ids,
                reason="offline deterministic pass recorded; no live counter-search was performed",
            )
        results.append(result)
        events.append({"status": "refutation_source_evaluated", **result.to_dict()})
        if result.contradiction_source_ids:
            events.append({"status": "contradiction_summary", "task_id": task.task_id, "contradiction_count": len(result.contradiction_source_ids)})
        for code in result.unresolved_gap_codes:
            events.append({"status": "unresolved_gap_recorded", "task_id": task.task_id, "gap_code": code})

    unresolved_gap_count = sum(len(result.unresolved_gap_codes) for result in results)
    contradiction_count = sum(len(result.contradiction_source_ids) for result in results)
    readiness = "blocked" if unresolved_gap_count or any(result.status == "blocked" for result in results) else "completed"
    reason = "unresolved gaps block readiness" if readiness == "blocked" else "refutation pass completed without detected contradiction"
    events.append({"status": "refutation_pass_completed", "readiness": readiness, "reason": reason})
    return RefutationLoopReport(
        tasks=tasks,
        results=tuple(results),
        readiness=readiness,
        reason=reason,
        contradiction_count=contradiction_count,
        unresolved_gap_count=unresolved_gap_count,
        events=tuple(events),
    )


def _accepted_material_source_ids(source_decision_ledger: SourceDecisionLedger | None) -> frozenset[str]:
    if source_decision_ledger is None:
        return frozenset()
    return frozenset(
        decision.source_id
        for decision in source_decision_ledger.decisions
        if decision.accepted and decision.decision == "accepted" and decision.source_role in _MATERIAL_ROLES
    )
