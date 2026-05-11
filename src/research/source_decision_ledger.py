"""Source decision ledger with canonical citation identity.

This is a backend-only, deterministic adapter around the existing source audit.
It does not perform network calls and does not contain benchmark/domain-specific
runtime branches.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from src.evidence.artifact import EvidenceRef, Finding
from src.research.citation_resolver import CitationCandidate, ResolvedCitation, resolve_citation
from src.research.karpathy_autoresearch import ResearchQualityAudit, SourceEvaluation


MATERIAL_SOURCE_ROLES = {"core_evidence", "comparison"}
BACKGROUND_SOURCE_ROLES = {"background", "rejected", "off_topic"}
_STABLE_IDENTITY_SOURCE_KINDS = {"paper", "doi", "review", "academic", "trial", "patent", "dataset"}
_STABLE_IDENTITY_SOURCE_CLASSES = {"peer_reviewed", "trial", "patent", "dataset"}


@dataclass(frozen=True)
class SourceDecision:
    source_id: str
    route_id: str | None
    raw_title: str
    raw_url: str
    canonical_id: str | None
    canonical_url: str | None
    identifier_kind: str
    source_kind: str
    source_role: str
    authority_level: str
    accepted: bool
    decision: str
    relevance_score: float
    reason: str
    rejection_codes: tuple[str, ...]
    quote_present: bool
    locator_present: bool
    resolver_status: str
    resolver_reason: str = ""
    facet_ids: tuple[str, ...] = field(default_factory=tuple)
    route_facet_id: str | None = None
    route_intent: str | None = None
    route_source_class: str | None = None
    route_authority_requirement: str | None = None
    route_acceptance_rules: tuple[str, ...] = field(default_factory=tuple)
    route_purpose: str | None = None
    route_backend: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "route_id": self.route_id,
            "raw_title": self.raw_title,
            "raw_url": self.raw_url,
            "canonical_id": self.canonical_id,
            "canonical_url": self.canonical_url,
            "identifier_kind": self.identifier_kind,
            "source_kind": self.source_kind,
            "source_role": self.source_role,
            "authority_level": self.authority_level,
            "accepted": self.accepted,
            "decision": self.decision,
            "relevance_score": self.relevance_score,
            "reason": self.reason,
            "rejection_codes": list(self.rejection_codes),
            "quote_present": self.quote_present,
            "locator_present": self.locator_present,
            "resolver_status": self.resolver_status,
            "resolver_reason": self.resolver_reason,
            "facet_ids": list(self.facet_ids),
            "route_facet_id": self.route_facet_id,
            "route_intent": self.route_intent,
            "route_source_class": self.route_source_class,
            "route_authority_requirement": self.route_authority_requirement,
            "route_acceptance_rules": list(self.route_acceptance_rules),
            "route_purpose": self.route_purpose,
            "route_backend": self.route_backend,
        }


@dataclass(frozen=True)
class SourceDecisionLedger:
    decisions: tuple[SourceDecision, ...]

    @property
    def accepted_source_ids(self) -> frozenset[str]:
        return frozenset(decision.source_id for decision in self.decisions if decision.accepted)

    @property
    def rejected_source_reasons(self) -> dict[str, str]:
        return {
            decision.source_id: decision.reason
            for decision in self.decisions
            if not decision.accepted
        }

    def summary(self) -> dict[str, Any]:
        accepted = [item for item in self.decisions if item.accepted]
        needs_review = [item for item in self.decisions if item.decision == "needs_review"]
        rejected = [item for item in self.decisions if item.decision == "rejected"]
        blocking_unresolved = [
            item
            for item in self.decisions
            if "canonical_identity_unresolved" in item.rejection_codes
        ]
        by_role: dict[str, int] = {}
        by_identifier_kind: dict[str, int] = {}
        by_route_facet: dict[str, int] = {}
        by_route_facet_id: dict[str, dict[str, Any]] = {}
        by_route_intent: dict[str, int] = {}
        by_route_source_class: dict[str, int] = {}
        for item in self.decisions:
            by_role[item.source_role] = by_role.get(item.source_role, 0) + 1
            by_identifier_kind[item.identifier_kind] = by_identifier_kind.get(item.identifier_kind, 0) + 1
            if item.route_facet_id:
                by_route_facet[item.route_facet_id] = by_route_facet.get(item.route_facet_id, 0) + 1
                bucket = by_route_facet_id.setdefault(item.route_facet_id, _empty_route_facet_summary())
                bucket["decision_count"] += 1
                if item.accepted:
                    bucket["accepted_count"] += 1
                    bucket["accepted_source_ids"].append(item.source_id)
                if item.decision == "rejected":
                    bucket["rejected_count"] += 1
                    bucket["rejected_source_ids"].append(item.source_id)
                if item.decision == "needs_review":
                    bucket["needs_review_count"] += 1
                    bucket["needs_review_source_ids"].append(item.source_id)
                if "canonical_identity_unresolved" in item.rejection_codes:
                    bucket["blocking_unresolved_canonical_count"] += 1
                if item.route_id and item.route_id not in bucket["route_ids"]:
                    bucket["route_ids"].append(item.route_id)
            if item.route_intent:
                by_route_intent[item.route_intent] = by_route_intent.get(item.route_intent, 0) + 1
            if item.route_source_class:
                by_route_source_class[item.route_source_class] = by_route_source_class.get(item.route_source_class, 0) + 1
        route_facet_statuses = {
            facet_id: _route_facet_status(bucket)
            for facet_id, bucket in by_route_facet_id.items()
        }
        return {
            "decision_count": len(self.decisions),
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
            "needs_review_count": len(needs_review),
            "blocking_unresolved_canonical_count": len(blocking_unresolved),
            "accepted_source_ids": [item.source_id for item in accepted],
            "needs_review_source_ids": [item.source_id for item in needs_review],
            "source_role_counts": by_role,
            "identifier_kind_counts": by_identifier_kind,
            "route_facet_counts": by_route_facet,
            "by_route_facet_id": by_route_facet_id,
            "route_facet_statuses": route_facet_statuses,
            "route_intent_counts": by_route_intent,
            "route_source_class_counts": by_route_source_class,
        }

    def quality_gate_events(self) -> tuple[dict[str, Any], ...]:
        return (
            {
                "event": "research_progress",
                "stage": "quality_gate",
                "status": "source_decision_ledger_built",
                **self.summary(),
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "decisions": [decision.to_dict() for decision in self.decisions],
            "summary": self.summary(),
        }


def _empty_route_facet_summary() -> dict[str, Any]:
    return {
        "decision_count": 0,
        "accepted_count": 0,
        "rejected_count": 0,
        "needs_review_count": 0,
        "blocking_unresolved_canonical_count": 0,
        "accepted_source_ids": [],
        "rejected_source_ids": [],
        "needs_review_source_ids": [],
        "route_ids": [],
    }


def _route_facet_status(summary: Mapping[str, Any]) -> str:
    if int(summary.get("decision_count") or 0) <= 0:
        return "no_decisions"
    if int(summary.get("needs_review_count") or 0) or int(summary.get("blocking_unresolved_canonical_count") or 0):
        return "needs_review"
    if int(summary.get("accepted_count") or 0):
        return "satisfied"
    return "gap"


def facet_gap_scheduler_report(
    planned_query_routes: Any,
    *,
    source_decision_summary: Mapping[str, Any] | None = None,
    claim_coverage: Mapping[str, Any] | None = None,
    refutation_summary: Mapping[str, Any] | None = None,
    max_followups: int = 3,
) -> dict[str, Any]:
    """Build a bounded deterministic follow-up schedule for unresolved route facets.

    This is deliberately offline and domain-general: it only inspects planned
    query route metadata plus already-computed ledger/claim/refutation summaries.
    """

    routes = _planned_routes(planned_query_routes)
    summary = source_decision_summary or {}
    facet_summaries = summary.get("by_route_facet_id") if isinstance(summary.get("by_route_facet_id"), Mapping) else {}
    facet_statuses = summary.get("route_facet_statuses") if isinstance(summary.get("route_facet_statuses"), Mapping) else {}
    coverage_gap = _claim_coverage_has_gap(claim_coverage or {})
    refutation_gap = _refutation_has_gap(refutation_summary or {})

    first_route_by_facet: dict[str, Mapping[str, Any]] = {}
    for route in routes:
        facet_id = str(route.get("facet_id") or "").strip()
        if facet_id and facet_id not in first_route_by_facet:
            first_route_by_facet[facet_id] = route

    candidates: list[dict[str, Any]] = []
    for facet_id, route in first_route_by_facet.items():
        facet_summary = facet_summaries.get(facet_id) if isinstance(facet_summaries, Mapping) else None
        status = str(facet_statuses.get(facet_id) or _route_facet_status(facet_summary or {}))
        if status == "satisfied":
            continue
        reason_codes = [_reason_code_for_route_facet_status(status)]
        if coverage_gap:
            reason_codes.append("claim_coverage_gap")
        intent = str(route.get("intent") or "").strip()
        if refutation_gap and (intent.casefold() in {"refutation", "refute"} or facet_id == "counter_evidence"):
            reason_codes.append("refutation_gap")
        candidates.append(
            {
                "facet_id": facet_id,
                "route_id": str(route.get("route_id") or "") or None,
                "query": str(route.get("query") or ""),
                "intent": intent,
                "reason_codes": reason_codes,
                "_sort_key": _facet_gap_sort_key(status, facet_id, intent),
            }
        )

    candidates.sort(key=lambda item: item["_sort_key"])
    limit = max(0, int(max_followups or 0))
    scheduled = []
    for priority, candidate in enumerate(candidates[:limit]):
        row = dict(candidate)
        row.pop("_sort_key", None)
        row["priority"] = priority
        scheduled.append(row)

    return {
        "status": "facet_gaps_pending" if candidates else "complete",
        "candidate_count": len(candidates),
        "scheduled_count": len(scheduled),
        "max_followups": limit,
        "scheduled_followups": scheduled,
    }


def _planned_routes(planned_query_routes: Any) -> tuple[Mapping[str, Any], ...]:
    raw_routes = getattr(planned_query_routes, "query_routes", planned_query_routes)
    return tuple(route for route in (raw_routes or ()) if isinstance(route, Mapping))


def _claim_coverage_has_gap(claim_coverage: Mapping[str, Any]) -> bool:
    unsupported = int(claim_coverage.get("unsupported_count") or 0)
    partial = int(claim_coverage.get("partial_count") or 0)
    supported_ratio = float(claim_coverage.get("supported_ratio") or 0.0)
    row_count = int(claim_coverage.get("row_count") or 0)
    return unsupported > 0 or partial > 0 or (row_count > 0 and supported_ratio < 1.0)


def _refutation_has_gap(refutation_summary: Mapping[str, Any]) -> bool:
    return str(refutation_summary.get("readiness") or "").casefold() == "blocked" or int(refutation_summary.get("unresolved_gap_count") or 0) > 0


def _reason_code_for_route_facet_status(status: str) -> str:
    normalized = str(status or "").casefold().strip()
    if normalized == "needs_review":
        return "route_facet_needs_review"
    if normalized == "no_decisions":
        return "route_facet_no_decisions"
    return "route_facet_gap"


def _facet_gap_sort_key(status: str, facet_id: str, intent: str) -> tuple[int, int, str]:
    status_rank = {"needs_review": 0, "gap": 1, "no_decisions": 2}.get(str(status or "").casefold(), 3)
    intent_rank = 0 if str(intent or "").casefold() in {"refutation", "refute"} or facet_id == "counter_evidence" else 1
    return (status_rank, intent_rank, facet_id)


def build_source_decision_ledger(
    findings: Sequence[Finding],
    *,
    audit: ResearchQualityAudit,
    plan: Any | None = None,
) -> SourceDecisionLedger:
    evaluations_by_id = {item.source_id: item for item in audit.source_evaluations}
    routes_by_id, routes_by_query = _routes(plan)
    decisions = []
    for ref in _dedupe_refs(findings):
        evaluation = evaluations_by_id.get(ref.id)
        route_id = _route_id_for_ref(ref, routes_by_query)
        route = routes_by_id.get(route_id or "") or {}
        resolution = resolve_citation(
            CitationCandidate(
                source_id=ref.id,
                title=str(ref.source_title or ""),
                url=str(ref.source_url or ""),
                quote=str(ref.quote or ""),
                source_class=str(route.get("source_class") or _metadata(ref).get("source_class") or ""),
                route_id=route_id,
                metadata=_metadata(ref),
            )
        )
        decisions.append(_decision_for_ref(ref, evaluation, resolution, route_id=route_id, route=route))
    return SourceDecisionLedger(decisions=tuple(decisions))


def _decision_for_ref(
    ref: EvidenceRef,
    evaluation: SourceEvaluation | None,
    resolution: ResolvedCitation,
    *,
    route_id: str | None,
    route: Mapping[str, Any],
) -> SourceDecision:
    metadata = _metadata(ref)
    route_facet_id = _first_text(route.get("facet_id"), metadata.get("route_facet_id"), metadata.get("facet_id"))
    route_intent = _first_text(route.get("intent"), metadata.get("route_intent"), metadata.get("intent"))
    route_source_class = _first_text(route.get("source_class"), metadata.get("route_source_class"), metadata.get("source_class"))
    route_authority_requirement = _first_text(
        route.get("authority_requirement"),
        metadata.get("route_authority_requirement"),
        metadata.get("authority_requirement"),
    )
    route_acceptance_rules = _string_tuple(route.get("acceptance_rules") or metadata.get("route_acceptance_rules") or metadata.get("acceptance_rules"))
    route_purpose = _first_text(route.get("purpose"), metadata.get("route_purpose"), metadata.get("purpose"))
    route_backend = _first_text(route.get("backend"), metadata.get("route_backend"), metadata.get("backend"))
    source_kind = str(getattr(evaluation, "source_kind", "") or metadata.get("kind") or ref.provenance.get("kind") or "unknown")
    source_role = _source_role(ref, source_kind=source_kind)
    authority_level = _authority_level(ref, source_kind=source_kind)
    quote_present = bool(str(ref.quote or metadata.get("source_text") or "").strip())
    locator = str(ref.source_url or metadata.get("locator") or metadata.get("source") or metadata.get("url") or "").strip()
    locator_present = bool(locator)
    audit_accepted = bool(evaluation.accepted) if evaluation is not None else False
    rejection_codes: list[str] = []

    if not audit_accepted:
        rejection_codes.append("source_audit_rejected")
    if _requires_stable_identity(source_kind, route, resolution) and resolution.resolver_status != "resolved":
        rejection_codes.append("canonical_identity_unresolved")
    if source_role not in MATERIAL_SOURCE_ROLES:
        rejection_codes.append("non_material_source_role")
    if not quote_present:
        rejection_codes.append("missing_quote")
    if not locator_present:
        rejection_codes.append("missing_locator")

    accepted = not rejection_codes
    if accepted:
        decision = "accepted"
        reason = _join_reasons(evaluation.reason if evaluation is not None else "source accepted", "canonical identity resolved")
    elif "canonical_identity_unresolved" in rejection_codes:
        decision = "needs_review"
        reason = _join_reasons(
            evaluation.reason if evaluation is not None else "source audit unavailable",
            resolution.needs_review_reason or f"resolver_status={resolution.resolver_status}",
        )
    else:
        decision = "rejected"
        reason = _join_reasons(evaluation.reason if evaluation is not None else "source audit unavailable", ", ".join(rejection_codes))

    return SourceDecision(
        source_id=ref.id,
        route_id=route_id,
        raw_title=str(ref.source_title or ""),
        raw_url=locator,
        canonical_id=resolution.canonical_id,
        canonical_url=resolution.canonical_url,
        identifier_kind=resolution.identifier_kind,
        source_kind=source_kind,
        source_role=source_role,
        authority_level=authority_level,
        accepted=accepted,
        decision=decision,
        relevance_score=round(float(getattr(evaluation, "relevance_score", 0.0) or 0.0), 3),
        reason=reason,
        rejection_codes=tuple(rejection_codes),
        quote_present=quote_present,
        locator_present=locator_present,
        resolver_status=resolution.resolver_status,
        resolver_reason=resolution.needs_review_reason,
        facet_ids=tuple(getattr(evaluation, "facet_ids", ()) or ()),
        route_facet_id=route_facet_id,
        route_intent=route_intent,
        route_source_class=route_source_class,
        route_authority_requirement=route_authority_requirement,
        route_acceptance_rules=route_acceptance_rules,
        route_purpose=route_purpose,
        route_backend=route_backend,
    )


def _requires_stable_identity(source_kind: str, route: Mapping[str, Any], resolution: ResolvedCitation) -> bool:
    source_class = str(route.get("source_class") or "").casefold()
    if resolution.resolver_status in {"redirect_only", "unsupported", "ambiguous"}:
        return True
    return source_kind.casefold() in _STABLE_IDENTITY_SOURCE_KINDS or source_class in _STABLE_IDENTITY_SOURCE_CLASSES


def _source_role(ref: EvidenceRef, *, source_kind: str) -> str:
    provenance = ref.provenance or {}
    metadata = _metadata(ref)
    raw = str(provenance.get("source_role") or provenance.get("role") or metadata.get("source_role") or "").casefold().strip()
    aliases = {
        "": "core_evidence" if source_kind not in {"web", "generated", "mock", "empty"} else "background",
        "primary": "core_evidence",
        "direct": "core_evidence",
        "core": "core_evidence",
        "accepted": "core_evidence",
        "comparison": "comparison",
        "comparative": "comparison",
        "background": "background",
        "rejected": "rejected",
        "off_topic": "off_topic",
        "off-topic": "off_topic",
    }
    return aliases.get(raw, raw or "background")


def _authority_level(ref: EvidenceRef, *, source_kind: str) -> str:
    provenance = ref.provenance or {}
    metadata = _metadata(ref)
    raw = str(provenance.get("authority_level") or metadata.get("authority_level") or "").casefold().strip()
    if raw in {"high", "medium", "low", "unknown"}:
        return raw
    if str(ref.source_grade or "").upper() == "A" or source_kind in {"doi", "paper", "trial"}:
        return "high"
    if str(ref.source_grade or "").upper() in {"B", "C"}:
        return "medium"
    return "unknown"


def _route_id_for_ref(ref: EvidenceRef, routes_by_query: Mapping[str, Mapping[str, Any]]) -> str | None:
    metadata = _metadata(ref)
    route_id = metadata.get("route_id") or (ref.provenance or {}).get("route_id")
    if route_id:
        return str(route_id)
    query = str(metadata.get("query") or "")
    route = routes_by_query.get(query)
    if route and route.get("route_id"):
        return str(route.get("route_id"))
    return None


def _routes(plan: Any | None) -> tuple[dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    by_id: dict[str, Mapping[str, Any]] = {}
    by_query: dict[str, Mapping[str, Any]] = {}
    for route in getattr(plan, "query_routes", ()) or ():
        if not isinstance(route, Mapping):
            continue
        route_id = str(route.get("route_id") or "")
        query = str(route.get("query") or "")
        if route_id:
            by_id[route_id] = route
        if query:
            by_query[query] = route
    return by_id, by_query


def _metadata(ref: EvidenceRef) -> dict[str, Any]:
    provenance = ref.provenance or {}
    metadata = provenance.get("metadata") if isinstance(provenance.get("metadata"), dict) else {}
    merged = dict(metadata)
    # Provenance.as_dict() flattens metadata to the top level, while some older
    # callers still provide a nested metadata dict. Accept both shapes so route
    # and source-channel metadata survive into the source-decision ledger.
    for key in (
        "query",
        "route_id",
        "route_facet_id",
        "route_intent",
        "route_source_class",
        "route_authority_requirement",
        "route_acceptance_rules",
        "route_purpose",
        "route_backend",
        "facet_id",
        "intent",
        "source_class",
        "authority_requirement",
        "acceptance_rules",
        "purpose",
        "backend",
        "authority_level",
        "source_role",
        "source",
        "url",
        "locator",
        "source_text",
        "title",
        "abstract",
        "snippet",
        "description",
        "doi",
        "pmid",
        "pmcid",
        "arxiv",
    ):
        if key in provenance and key not in merged:
            merged[key] = provenance[key]
    return merged


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, Iterable):
        return tuple(str(item).strip() for item in value if str(item or "").strip())
    text = str(value).strip()
    return (text,) if text else ()


def _dedupe_refs(findings: Sequence[Finding]) -> tuple[EvidenceRef, ...]:
    refs: list[EvidenceRef] = []
    seen: set[str] = set()
    for finding in findings:
        for ref in finding.support:
            if ref.id in seen:
                continue
            seen.add(ref.id)
            refs.append(ref)
    return tuple(refs)


def _join_reasons(*parts: str) -> str:
    return "; ".join(str(part).strip() for part in parts if str(part or "").strip())
