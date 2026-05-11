"""Backend research audit appendix formatting.

This module is intentionally presentation-only: it consumes already-built
research-engine artifacts and renders a bounded markdown appendix without
changing retrieval, provider routing, or fixture selection.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence


def build_research_audit_appendix_payload(
    *,
    query_route_ledger: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    source_decision_summary: Mapping[str, Any] | None = None,
    claim_evidence_summary: Mapping[str, Any] | None = None,
    refutation_loop_summary: Mapping[str, Any] | None = None,
    evidence_ledger_metrics: Mapping[str, Any] | None = None,
    evidence_ledger_readiness: str | None = None,
    research_readiness_decision: Mapping[str, Any] | None = None,
    research_process_completeness: Mapping[str, Any] | None = None,
    max_routes: int = 8,
) -> dict[str, Any]:
    """Return a JSON-safe, size-bounded audit appendix payload."""

    route_input = query_route_ledger or []
    if isinstance(route_input, Mapping):
        raw_routes = route_input.get("routes") or []
        route_count = int(route_input.get("route_count") or len(raw_routes))
    else:
        raw_routes = list(route_input)
        route_count = len(raw_routes)
    routes = [_route_summary(route) for route in list(raw_routes)[:max_routes] if isinstance(route, Mapping)]
    return {
        "schema_version": "research-audit-appendix.v1",
        "route_ledger": {
            "route_count": route_count,
            "shown_count": len(routes),
            "routes": routes,
        },
        "source_decision_summary": dict(source_decision_summary or {}),
        "claim_evidence_matrix_summary": dict(claim_evidence_summary or {}),
        "refutation_loop_summary": dict(refutation_loop_summary or {}),
        "evidence_ledger": {
            "readiness": evidence_ledger_readiness or "unknown",
            "metrics": dict(evidence_ledger_metrics or {}),
        },
        "research_readiness_decision": dict(research_readiness_decision or {}),
        "research_process_completeness": dict(research_process_completeness or {}),
    }


def render_research_audit_appendix(payload: Mapping[str, Any]) -> str:
    """Render a concise markdown appendix from a payload."""

    if not payload:
        return ""
    route_ledger = _as_mapping(payload.get("route_ledger"))
    source_summary = _as_mapping(payload.get("source_decision_summary"))
    claim_summary = _as_mapping(payload.get("claim_evidence_matrix_summary"))
    refutation_summary = _as_mapping(payload.get("refutation_loop_summary"))
    evidence_ledger = _as_mapping(payload.get("evidence_ledger"))
    readiness = _as_mapping(payload.get("research_readiness_decision"))
    process_completeness = _as_mapping(payload.get("research_process_completeness"))

    lines = [
        "## Research Audit Appendix",
        "",
        "### Query Route Ledger",
        "",
        f"- Routes: {route_ledger.get('route_count', 0)} total; {route_ledger.get('shown_count', 0)} shown",
    ]
    routes = route_ledger.get("routes") or []
    if routes:
        lines.extend(["", "| Route ID | Intent | Source class | Backend | Purpose |", "| --- | --- | --- | --- | --- |"])
        for route in routes:
            route_map = _as_mapping(route)
            lines.append(
                "| "
                f"{_cell(route_map.get('route_id'))} | "
                f"{_cell(route_map.get('intent'))} | "
                f"{_cell(route_map.get('source_class'))} | "
                f"{_cell(route_map.get('backend'))} | "
                f"{_cell(route_map.get('purpose'))} |"
            )
    lines.extend(
        [
            "",
            "### Source Decision Summary",
            "",
            f"- Decisions: {source_summary.get('decision_count', 0)}",
            f"- Accepted: {source_summary.get('accepted_count', 0)}",
            f"- Needs review: {source_summary.get('needs_review_count', 0)}",
            f"- Rejected: {source_summary.get('rejected_count', 0)}",
            f"- Blocking unresolved canonical IDs: {source_summary.get('blocking_unresolved_canonical_count', 0)}",
            "",
            "### Claim / Refutation / Evidence Readiness",
            "",
            f"- Claim gate: {claim_summary.get('decision', claim_summary.get('readiness', 'unknown'))}",
            f"- Supported claims: {claim_summary.get('supported_count', 0)} / {claim_summary.get('row_count', 0)}",
            f"- Refutation readiness: {refutation_summary.get('readiness', 'unknown')}",
            f"- Evidence ledger readiness: {evidence_ledger.get('readiness', 'unknown')}",
            f"- Process completeness: {process_completeness.get('readiness', 'unknown')} (score={process_completeness.get('score', 'unknown')})",
            f"- Research readiness: {readiness.get('readiness', 'unknown')} ({readiness.get('stop_state', 'unknown')})",
        ]
    )
    reasons = readiness.get("reasons") or []
    if reasons:
        lines.append(f"- Readiness reasons: {'; '.join(str(reason) for reason in reasons)}")
    metrics = _as_mapping(evidence_ledger.get("metrics"))
    if metrics:
        lines.extend(["", "### Evidence Ledger Metrics", ""])
        for key in sorted(metrics):
            lines.append(f"- {key}: {metrics[key]}")
    process_metrics = _as_mapping(process_completeness.get("metrics"))
    if process_completeness:
        lines.extend(["", "### Process Completeness", ""])
        lines.append(f"- Present steps: {', '.join(str(step) for step in process_completeness.get('present_steps', []) or [])}")
        lines.append(f"- Missing steps: {', '.join(str(step) for step in process_completeness.get('missing_steps', []) or []) or 'none'}")
        for key in sorted(process_metrics):
            lines.append(f"- {key}: {process_metrics[key]}")
    return "\n".join(lines).strip() + "\n"


def _route_summary(route: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "route_id": route.get("route_id", ""),
        "route_version": route.get("route_version", ""),
        "query": route.get("query", ""),
        "intent": route.get("intent", ""),
        "source_class": route.get("source_class", ""),
        "backend": route.get("backend", ""),
        "purpose": route.get("purpose", ""),
        "continue_reason": route.get("continue_reason", ""),
        "acceptance_rules": list(route.get("acceptance_rules") or []),
        "reject_patterns": list(route.get("reject_patterns") or []),
    }


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _cell(value: Any) -> str:
    return " ".join(str(value or "").replace("|", "\\|").split())
