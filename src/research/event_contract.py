"""Backend research-event contract validation.

The validator is intentionally lightweight and deterministic.  It validates the
research-engine stream produced by the backend before UI/Tauri code sees it;
unknown non-research application events remain out of scope.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


RESEARCH_PROGRESS_EVENT = "research_progress"
TERMINAL_RESEARCH_EVENTS = {"research_quality_ready", "research_quality_needs_review"}
BASE_REQUIRED_FIELDS = (
    "event",
    "status",
    "stage",
    "research_session_id",
    "app_run_id",
    "memory_policy",
    "topic_anchor",
)


@dataclass(frozen=True)
class EventContractDecision:
    in_scope: bool
    valid: bool
    missing_fields: tuple[str, ...] = field(default_factory=tuple)
    error_codes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "in_scope": self.in_scope,
            "valid": self.valid,
            "missing_fields": list(self.missing_fields),
            "error_codes": list(self.error_codes),
        }


def validate_research_event_contract(event: Mapping[str, Any]) -> EventContractDecision:
    """Validate one backend research/quality event payload.

    Non-research application events are treated as out-of-scope so the contract
    can be wired into generic progress emission without taking over UI events.
    """

    event_name = str(event.get("event") or "")
    if event_name != RESEARCH_PROGRESS_EVENT and event_name not in TERMINAL_RESEARCH_EVENTS:
        return EventContractDecision(in_scope=False, valid=True)

    missing: list[str] = []
    codes: list[str] = []
    _require(event, BASE_REQUIRED_FIELDS, missing, codes)

    status = str(event.get("status") or "")
    if event_name in TERMINAL_RESEARCH_EVENTS:
        _require(
            event,
            (
                "research_quality_readiness",
                "research_readiness_decision",
                "research_process_completeness",
            ),
            missing,
            codes,
        )
        decision = event.get("research_readiness_decision")
        if isinstance(decision, Mapping):
            _require(decision, ("readiness", "stop_state", "reasons"), missing, codes, prefix="research_readiness_decision")
    elif status == "research_plan_ready":
        if _empty(event.get("queries")) and _empty(event.get("query_routes")):
            missing.append("queries_or_query_routes")
            codes.append("missing:queries_or_query_routes")
        if _empty(event.get("query_count")):
            missing.append("query_count")
            codes.append("missing:query_count")
    elif status == "query_route_ledger_built":
        _require(event, ("route_count", "route_ids"), missing, codes)
    elif status == "source_decision_ledger_built":
        _require_present(event, ("by_route_facet_id", "route_facet_statuses"), missing, codes)
    elif status == "claim_evidence_gate":
        _require_present(event, ("claim_verification_summary", "citation_verification_summary"), missing, codes)
    elif status == "facet_gap_scheduler_report":
        _require_present(
            event,
            (
                "facet_gap_scheduler_report",
                "by_route_facet_id",
                "route_facet_statuses",
                "claim_verification_summary",
                "citation_verification_summary",
            ),
            missing,
            codes,
        )
    elif status == "searching":
        _require(event, ("query", "query_index", "query_count"), missing, codes)
        if "route_id" in event and _empty(event.get("route_id")):
            missing.append("route_id")
            codes.append("missing:route_id")
    elif status in {"source_resolved", "source_decision"}:
        _require(event, ("source_id", "route_id", "decision", "reason"), missing, codes)
        if _empty(event.get("canonical_id")) and _empty(event.get("resolver_status")):
            missing.append("canonical_id_or_resolver_status")
            codes.append("missing:canonical_id_or_resolver_status")
    elif status.startswith("refutation_"):
        if _empty(event.get("task_id")) and _empty(event.get("readiness")) and _empty(event.get("status")):
            missing.append("refutation_task_or_readiness")
            codes.append("missing:refutation_task_or_readiness")
    elif status == "research_process_completeness":
        _require(event, ("score", "readiness"), missing, codes)
        if "missing_steps" not in event:
            missing.append("missing_steps")
            codes.append("missing:missing_steps")

    return EventContractDecision(
        in_scope=True,
        valid=not missing,
        missing_fields=tuple(dict.fromkeys(missing)),
        error_codes=tuple(dict.fromkeys(codes)),
    )


def assert_research_event_contract(event: Mapping[str, Any]) -> dict[str, Any]:
    """Return a JSON-safe copy or raise ValueError with stable missing codes."""

    decision = validate_research_event_contract(event)
    if decision.in_scope and not decision.valid:
        raise ValueError("research_event_contract_invalid: " + ",".join(decision.error_codes))
    return dict(event)


def _require(
    event: Mapping[str, Any],
    fields: tuple[str, ...],
    missing: list[str],
    codes: list[str],
    *,
    prefix: str = "",
) -> None:
    for field_name in fields:
        value = event.get(field_name)
        qualified = f"{prefix}.{field_name}" if prefix else field_name
        if _empty(value):
            missing.append(qualified)
            codes.append(f"missing:{qualified}")


def _require_present(
    event: Mapping[str, Any],
    fields: tuple[str, ...],
    missing: list[str],
    codes: list[str],
    *,
    prefix: str = "",
) -> None:
    for field_name in fields:
        qualified = f"{prefix}.{field_name}" if prefix else field_name
        if field_name not in event or event.get(field_name) is None:
            missing.append(qualified)
            codes.append(f"missing:{qualified}")


def _empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False
