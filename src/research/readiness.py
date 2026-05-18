"""Research-quality readiness aggregator.

This module centralizes the backend-only terminal decision for research-quality
runs. It is generic, JSON-serializable, deterministic, and never infers a
benchmark/domain fixture from topic text.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


READY = "ready"
NEEDS_REVIEW = "needs_review"
BLOCKED = "blocked"


@dataclass(frozen=True)
class ResearchReadinessInput:
    source_audit_summary: Mapping[str, Any] = field(default_factory=dict)
    source_decision_summary: Mapping[str, Any] = field(default_factory=dict)
    claim_evidence_summary: Mapping[str, Any] = field(default_factory=dict)
    evidence_ledger_readiness: str = ""
    evidence_ledger_metrics: Mapping[str, Any] = field(default_factory=dict)
    refutation_loop_readiness: str = ""
    refutation_loop_summary: Mapping[str, Any] = field(default_factory=dict)
    max_plus_benchmark_decision: str | None = None
    max_plus_benchmark_metrics: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_audit_summary": dict(self.source_audit_summary),
            "source_decision_summary": dict(self.source_decision_summary),
            "claim_evidence_summary": dict(self.claim_evidence_summary),
            "evidence_ledger_readiness": self.evidence_ledger_readiness,
            "evidence_ledger_metrics": dict(self.evidence_ledger_metrics),
            "refutation_loop_readiness": self.refutation_loop_readiness,
            "refutation_loop_summary": dict(self.refutation_loop_summary),
            "max_plus_benchmark_decision": self.max_plus_benchmark_decision,
            "max_plus_benchmark_metrics": dict(self.max_plus_benchmark_metrics or {}),
        }


@dataclass(frozen=True)
class ResearchReadinessDecision:
    readiness: str
    stop_state: str
    reasons: tuple[str, ...]
    metrics: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "readiness": self.readiness,
            "stop_state": self.stop_state,
            "reasons": list(self.reasons),
            "metrics": dict(self.metrics),
        }

    def terminal_event_name(self) -> str:
        return "research_quality_ready" if self.readiness == READY else "research_quality_needs_review"


def decide_research_readiness(readiness_input: ResearchReadinessInput) -> ResearchReadinessDecision:
    """Return the one terminal quality decision from all backend sub-gates."""

    reasons: list[str] = []
    blocking = False

    source_audit = readiness_input.source_audit_summary or {}
    if source_audit and not _boolish(source_audit.get("passed"), default=True):
        reasons.append("source_audit_summary.passed=false")
        blocking = True

    source_decision = readiness_input.source_decision_summary or {}
    unresolved = _number(source_decision.get("blocking_unresolved_canonical_count"))
    needs_review_sources = _number(source_decision.get("needs_review_count"))
    if unresolved > 0:
        reasons.append(f"source_decision_summary.blocking_unresolved_canonical_count={_compact_number(unresolved)}")
        blocking = True
    if needs_review_sources > 0:
        reasons.append(f"source_decision_summary.needs_review_count={_compact_number(needs_review_sources)}")

    claim_summary = readiness_input.claim_evidence_summary or {}
    if claim_summary and not _boolish(claim_summary.get("passed"), default=True):
        reasons.append("claim_evidence_summary.passed=false")
        blocking = True
    supported_claim_count = _number(claim_summary.get("supported_count"))
    accepted_source_count = _accepted_source_count(source_audit, source_decision)
    if supported_claim_count > 0 and accepted_source_count == 0:
        reasons.append(
            "claim_evidence_summary.supported_count_without_accepted_sources="
            f"{_compact_number(supported_claim_count)}"
        )

    ledger_readiness = _normalized(readiness_input.evidence_ledger_readiness)
    if ledger_readiness and ledger_readiness != READY:
        reasons.append(f"evidence_ledger_readiness={ledger_readiness}")
        if ledger_readiness == BLOCKED:
            blocking = True
    evidence_metrics = readiness_input.evidence_ledger_metrics or {}
    expected_claim_gap_count = _number(evidence_metrics.get("expected_claim_gap_count"))
    expected_claim_count = _number(evidence_metrics.get("expected_claim_count"))
    expected_claim_traceability_score = _number(evidence_metrics.get("expected_claim_traceability_score"))
    if expected_claim_gap_count > 0:
        reasons.append(f"evidence_ledger.expected_claim_gap_count={_compact_number(expected_claim_gap_count)}")
    elif expected_claim_count > 0 and expected_claim_traceability_score < 1.0:
        reasons.append(
            "evidence_ledger.expected_claim_traceability_score="
            f"{_compact_number(expected_claim_traceability_score)}"
        )

    refutation_readiness = _normalized(readiness_input.refutation_loop_readiness)
    if refutation_readiness and refutation_readiness not in {"completed", "skipped", READY, "pass", "passed"}:
        reasons.append(f"refutation_loop_readiness={refutation_readiness}")
        if refutation_readiness == BLOCKED:
            blocking = True

    benchmark_decision = _normalized(readiness_input.max_plus_benchmark_decision)
    if benchmark_decision and benchmark_decision not in {"keep", READY, "pass", "passed"}:
        reasons.append(f"max_plus_benchmark_decision={benchmark_decision}")
        if benchmark_decision == BLOCKED:
            blocking = True

    if blocking:
        readiness = BLOCKED
        stop_state = "blocked_before_council"
    elif reasons:
        readiness = NEEDS_REVIEW
        stop_state = "needs_review_before_council"
    else:
        readiness = READY
        stop_state = "before_council"
        reasons.append("all_configured_research_quality_gates_ready")

    return ResearchReadinessDecision(
        readiness=readiness,
        stop_state=stop_state,
        reasons=tuple(reasons),
        metrics=_metrics(readiness_input),
    )


def _accepted_source_count(source_audit: Mapping[str, Any], source_decision: Mapping[str, Any]) -> float | None:
    """Return the accepted material source count used by claim-readiness guards.

    The source-decision ledger is preferred because it applies the accepted,
    non-background, canonical/locator/quote checks. Fall back to the legacy
    source-audit count only when the ledger summary is unavailable. If neither
    summary exposes a count, return None so legacy callers are not penalized for
    missing telemetry.
    """

    if "accepted_count" in source_decision:
        return _number(source_decision.get("accepted_count"))
    if "accepted_source_count" in source_audit:
        return _number(source_audit.get("accepted_source_count"))
    return None


def _metrics(readiness_input: ResearchReadinessInput) -> dict[str, Any]:
    source_decision = readiness_input.source_decision_summary or {}
    claim_summary = readiness_input.claim_evidence_summary or {}
    evidence_metrics = readiness_input.evidence_ledger_metrics or {}
    benchmark_metrics = readiness_input.max_plus_benchmark_metrics or {}
    metrics: dict[str, Any] = {
        "source_decision_accepted_count": int(_number(source_decision.get("accepted_count"))),
        "source_decision_needs_review_count": int(_number(source_decision.get("needs_review_count"))),
        "source_decision_blocking_unresolved_canonical_count": int(_number(source_decision.get("blocking_unresolved_canonical_count"))),
        "claim_supported_ratio": float(_number(claim_summary.get("supported_ratio"))),
        "evidence_ledger_readiness": readiness_input.evidence_ledger_readiness,
        "refutation_loop_readiness": readiness_input.refutation_loop_readiness,
    }
    for key, value in evidence_metrics.items():
        metrics[f"evidence_ledger.{key}"] = value
    for key, value in benchmark_metrics.items():
        metrics[f"max_plus_benchmark.{key}"] = value
    return metrics


def _normalized(value: Any) -> str:
    return str(value or "").strip().casefold()


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _compact_number(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return str(value)


def _boolish(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "on", "pass", "passed", "ready"}
