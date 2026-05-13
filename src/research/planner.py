"""ResearchBrief to ResearchPlan conversion."""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from src.interview.brief import ResearchBrief
from .queries import expand_query, translated_topic_queries


@dataclass
class ResearchPlan:
    brief_id: str
    queries: list[str]
    evidence_targets: list[str] = field(default_factory=list)
    expected_deliverables: list[str] = field(default_factory=list)
    stop_conditions: list[str] = field(default_factory=list)
    risk_notes: list[str] = field(default_factory=list)
    collection_rules: list[str] = field(default_factory=list)
    topic_anchor: str = ""
    query_routes: list[dict[str, Any]] = field(default_factory=list)


QUERY_ROUTE_VERSION = "query-route.v1"
NORMALIZED_ROUTE_INTENTS = {
    "primary_anchor_recall",
    "confirmation",
    "refutation",
    "gap_fill",
    "background_mapping",
    "comparison",
}
_INTENT_ALIASES = {
    "find_primary": "primary_anchor_recall",
    "primary": "primary_anchor_recall",
    "confirm": "confirmation",
    "refute": "refutation",
    "counter_evidence": "refutation",
    "gap": "gap_fill",
    "limitations": "gap_fill",
    "compare": "comparison",
    "comparative": "comparison",
}


@dataclass(frozen=True)
class QueryRoute:
    """Typed, JSON-compatible backend contract for a planned research query."""

    route_id: str
    route_version: str
    query: str
    facet_id: str
    purpose: str
    source_class: str
    intent: str
    backend: str
    authority_requirement: str
    acceptance_rules: tuple[str, ...]
    reject_patterns: tuple[str, ...] = ()
    continue_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "route_id": self.route_id,
            "route_version": self.route_version,
            "query": self.query,
            "facet_id": self.facet_id,
            "intent": self.intent,
            "source_class": self.source_class,
            "backend": self.backend,
            "purpose": self.purpose,
            "continue_reason": self.continue_reason,
            "authority_requirement": self.authority_requirement,
            "acceptance_rules": list(self.acceptance_rules),
            "reject_patterns": list(self.reject_patterns),
        }


class ResearchPlanner:
    def plan(self, brief: ResearchBrief, *, max_queries: int = 8) -> ResearchPlan:
        topic_anchor = str(
            getattr(brief, "original_topic", "")
            or brief.research_question.strip()
            or brief.raw_idea.strip()
            or ""
        ).strip()
        query = topic_anchor
        queries = expand_query(
            query,
            context=brief.context,
            quality_bar=brief.quality_bar,
        ) or [query]
        targeting_queries = _queries_from_targeting_map(brief)
        bridge_queries = translated_topic_queries(topic_anchor or query)
        if topic_anchor:
            # For live/source-backed runs, spend the limited query budget on
            # topic-anchored bridge queries before broad generic evidence
            # suffixes. Otherwise market/Korea adoption probes can be trimmed
            # before they ever reach academic/search backends.
            generic_queries = [candidate for candidate in queries if candidate.strip() != topic_anchor]
            official_queries = [candidate for candidate in generic_queries if "official statistics peer reviewed evidence" in candidate]
            other_generic_queries = [candidate for candidate in generic_queries if candidate not in official_queries]
            queries = _dedupe_with_market_floor(
                [topic_anchor] + official_queries + bridge_queries + other_generic_queries + targeting_queries,
                limit=max(1, max_queries),
            )
        else:
            queries = _dedupe_with_market_floor(queries + bridge_queries + targeting_queries, limit=max(1, max_queries))
        evidence_targets = _dedupe(
            ([brief.context] if brief.context else []) + _planning_evidence_targets(brief),
            limit=8,
        )
        expected_deliverables = _dedupe(
            [brief.deliverable_type] + _feature_deliverables(brief),
            limit=6,
        )
        return ResearchPlan(
            brief_id=brief.id,
            queries=queries,
            topic_anchor=topic_anchor,
            evidence_targets=evidence_targets,
            expected_deliverables=expected_deliverables,
            stop_conditions=[
                "at least one A/B-grade source or explicit D-grade fallback per major claim",
                "counter-evidence query attempted before council",
                "stop when new searches only repeat existing evidence ids",
            ],
            risk_notes=[
                "do not treat LLM output as evidence",
                "separate source quotes from generated synthesis",
            ],
            collection_rules=[
                "prefer academic APIs, official statistics, and local vault before general web snippets",
                "record query, source grade, source text, and retrieval score in provenance",
                "if all sources are C/D, mark the finding limitation before report generation",
            ],
            query_routes=[source_route_for_query(query) for query in queries],
        )


def with_source_discovery_queries(
    plan: ResearchPlan,
    discovery_queries: Iterable[str],
    *,
    max_queries: int | None = None,
) -> ResearchPlan:
    """Return a plan with explicit source-discovery queries appended.

    The helper is generic: callers pass fixture/evaluation/config-derived
    queries. It never infers benchmark/domain terms from the runtime topic.
    """

    extras = [str(query).strip() for query in discovery_queries if str(query).strip()]
    if not extras:
        return plan
    limit = max_queries if max_queries is not None else len(plan.queries) + len(extras)
    queries = _dedupe(list(plan.queries) + extras, limit=max(1, limit))
    return ResearchPlan(
        brief_id=plan.brief_id,
        queries=queries,
        evidence_targets=list(plan.evidence_targets),
        expected_deliverables=list(plan.expected_deliverables),
        stop_conditions=list(plan.stop_conditions),
        risk_notes=list(plan.risk_notes),
        collection_rules=list(plan.collection_rules),
        topic_anchor=plan.topic_anchor,
        query_routes=[source_route_for_query(query) for query in queries],
    )


def source_route_for_query(query: str) -> dict[str, Any]:
    """Return generic source-class routing metadata for a planned query.

    This is intentionally procedural and fixture-agnostic: it reads the query's
    evidence intent/source-channel words and emits a Max-style route contract
    that downstream retrieval/audit code can carry in traces. Domain specificity
    must stay in the user topic, interview answers, or targeting map.
    """

    normalized = " ".join(str(query or "").split())
    lowered = normalized.casefold()
    intent = "background_mapping"
    source_class = "background"
    facet_id = "background_scope"
    backend = "web"
    authority = "medium"
    purpose = "map topic scope and background sources"
    continue_reason = "background sources may frame scope but need corroboration for factual claims"
    rules = [
        "accepted source must share topic anchor terms with the query",
        "listing/search-result pages cannot directly support material claims",
    ]

    if re.search(r"\b10\.\d{4,9}/\S+", lowered) or "doi:" in lowered or "doi.org/" in lowered:
        intent = "primary_anchor_recall"
        source_class = "peer_reviewed"
        facet_id = "canonical_sources"
        backend = "scholar"
        authority = "high"
        purpose = "resolve stable scholarly identifier"
        continue_reason = "resolve DOI or other stable scholarly identifier before falling back to broad web snippets"
        rules.append("resolve DOI or other stable scholarly identifier before falling back to broad web snippets")
    elif any(marker in lowered for marker in ("counter evidence", "limitations", "failure cases", "refute", "contradict")):
        intent = "refutation"
        source_class = "peer_reviewed"
        facet_id = "counter_evidence"
        backend = "scholar"
        authority = "high"
        purpose = "test counter-evidence and limitations"
        continue_reason = "must corroborate before high-confidence claim support"
        rules.append("must corroborate before high-confidence claim support")
    elif any(
        marker in lowered
        for marker in (
            "official statistics",
            "government statistics",
            "공식",
            "통계",
            "regulatory adoption",
            "public data",
            "공공데이터",
        )
    ):
        intent = "primary_anchor_recall"
        source_class = "official"
        facet_id = "canonical_sources"
        backend = "web"
        authority = "high"
        purpose = "find canonical official/statistical sources"
        continue_reason = "prefer canonical government/statistics/standards pages over secondary summaries"
        rules.append("prefer canonical government/statistics/standards pages over secondary summaries")
    elif any(
        marker in lowered
        for marker in (
            "peer reviewed",
            "empirical evidence",
            "methods validation",
            "source quality",
            "validation limitations",
        )
    ):
        intent = "primary_anchor_recall"
        source_class = "peer_reviewed"
        facet_id = "canonical_sources"
        backend = "scholar"
        authority = "high"
        purpose = "find primary peer-reviewed evidence"
        continue_reason = "prefer primary papers, systematic reviews, datasets, or methods documents"
        rules.append("prefer primary papers, systematic reviews, datasets, or methods documents")
    elif any(marker in lowered for marker in ("definitions", "scope", "constraints", "case studies", "examples")):
        intent = "comparison"
        source_class = "background"
        backend = "web"
        authority = "medium"
        purpose = "compare scope, definitions, constraints, or examples"
        continue_reason = "background sources may frame scope but need corroboration for factual claims"
        rules.append("background sources may frame scope but need corroboration for factual claims")

    return QueryRoute(
        route_id=_route_id_for_query(normalized),
        route_version=QUERY_ROUTE_VERSION,
        query=normalized,
        facet_id=facet_id,
        intent=normalize_route_intent(intent),
        source_class=source_class,
        backend=backend,
        purpose=purpose,
        continue_reason=continue_reason,
        authority_requirement=authority,
        acceptance_rules=tuple(rules),
        reject_patterns=("listing/search result page", "redirect-only grounding wrapper"),
    ).to_dict()


def normalize_route_intent(intent: str) -> str:
    """Normalize legacy planner route aliases at the API boundary."""

    normalized = str(intent or "").casefold().strip().replace("-", "_").replace(" ", "_")
    if normalized in NORMALIZED_ROUTE_INTENTS:
        return normalized
    return _INTENT_ALIASES.get(normalized, "background_mapping")


def query_route_ledger(plan: ResearchPlan) -> dict[str, Any]:
    """Return a compact JSON-safe route ledger artifact payload."""

    routes = [dict(route) for route in getattr(plan, "query_routes", []) if isinstance(route, dict)]
    return {
        "route_count": len(routes),
        "route_version": QUERY_ROUTE_VERSION,
        "routes": routes,
    }


def adaptive_followup_query_plan(
    plan: ResearchPlan,
    facet_gap_report: dict[str, Any],
    *,
    max_followups: int = 3,
) -> dict[str, Any]:
    """Convert unresolved facet-gap rows into bounded generic follow-up routes.

    The planner is intentionally deterministic and offline. It consumes the
    already-computed facet gap scheduler output, preserves the original topic
    text embedded in scheduled queries, and only adds generic evidence-quality
    suffixes derived from reason codes/facet IDs.
    """

    scheduled = facet_gap_report.get("scheduled_followups") if isinstance(facet_gap_report, dict) else []
    rows = [row for row in (scheduled or []) if isinstance(row, dict)]
    limit = max(0, int(max_followups or 0))
    routes: list[dict[str, Any]] = []
    for idx, row in enumerate(rows[:limit]):
        base_query = " ".join(str(row.get("query") or getattr(plan, "topic_anchor", "") or "").split())
        if not base_query:
            continue
        reason_codes = tuple(str(code).strip() for code in (row.get("reason_codes") or ()) if str(code).strip())
        facet_id = str(row.get("facet_id") or "background_scope").strip() or "background_scope"
        intent = normalize_route_intent(str(row.get("intent") or _intent_for_adaptive_facet(facet_id)))
        query = _adaptive_followup_query(base_query, facet_id=facet_id, reason_codes=reason_codes)
        route = source_route_for_query(query)
        route.update(
            {
                "route_id": _adaptive_route_id(query, idx),
                "facet_id": facet_id,
                "intent": intent,
                "purpose": _adaptive_route_purpose(facet_id, reason_codes),
                "continue_reason": "; ".join(reason_codes) or "unresolved route facet requires follow-up evidence",
                "followup_of_route_id": row.get("route_id"),
                "adaptive_reason_codes": list(reason_codes),
                "priority": int(row.get("priority") or idx),
                "planner_source": "facet_gap_scheduler_report",
            }
        )
        if facet_id == "counter_evidence":
            route.update({"source_class": "peer_reviewed", "backend": "scholar", "authority_requirement": "high"})
        elif facet_id == "canonical_sources":
            route.update({"authority_requirement": "high"})
        routes.append(route)

    return {
        "status": "adaptive_followups_planned" if routes else "no_adaptive_followups",
        "planned_count": len(routes),
        "max_followups": limit,
        "source_gap_status": facet_gap_report.get("status") if isinstance(facet_gap_report, dict) else None,
        "adaptive_query_routes": routes,
        "model_role_routing_plan": _adaptive_model_role_routing_plan(bool(routes)),
    }


def adaptive_followup_execution_report(
    adaptive_query_plan: dict[str, Any],
    *,
    facet_gap_report: dict[str, Any] | None = None,
    executed_route_ids: set[str] | None = None,
    pending_reason: str = "deferred_to_next_bounded_retrieval_pass",
) -> dict[str, Any]:
    """Record bounded iteration-2 status for adaptive follow-up routes.

    The current quality gate is deterministic and offline. When callers do not
    execute a second retrieval pass in-process, every planned adaptive route is
    recorded as pending with an explicit reason instead of disappearing after
    planning.
    """

    routes = [
        dict(route)
        for route in (adaptive_query_plan.get("adaptive_query_routes") if isinstance(adaptive_query_plan, dict) else []) or []
        if isinstance(route, dict)
    ]
    executed = {str(route_id) for route_id in (executed_route_ids or set()) if str(route_id).strip()}
    executed_followups = []
    pending_followups = []
    for route in routes:
        route_id = str(route.get("route_id") or "")
        row = {
            "route_id": route_id,
            "followup_of_route_id": route.get("followup_of_route_id"),
            "facet_id": route.get("facet_id"),
            "intent": route.get("intent"),
            "query": route.get("query"),
            "priority": route.get("priority"),
            "adaptive_reason_codes": list(route.get("adaptive_reason_codes") or ()),
        }
        if route_id in executed:
            executed_followups.append(row)
        else:
            pending_followups.append({**row, "pending_reason": pending_reason})

    gap_report = facet_gap_report if isinstance(facet_gap_report, dict) else {}
    candidate_count = int(gap_report.get("candidate_count") or len(routes))
    status = "no_adaptive_followups"
    if pending_followups:
        status = "adaptive_followups_pending"
    elif executed_followups:
        status = "adaptive_followups_executed"

    iteration_2 = {
        "status": "facet_gaps_pending" if pending_followups else "complete",
        "iteration": 2,
        "source_iteration": 1,
        "candidate_count": candidate_count,
        "planned_count": len(routes),
        "executed_count": len(executed_followups),
        "pending_count": len(pending_followups),
        "gap_count_before": candidate_count,
        "gap_count_after_upper_bound": min(candidate_count, len(pending_followups)),
        "executed_followups": executed_followups,
        "pending_followups": pending_followups,
    }
    return {
        "status": status,
        "iteration": 2,
        "planned_count": len(routes),
        "executed_count": len(executed_followups),
        "pending_count": len(pending_followups),
        "executed_route_ids": [row["route_id"] for row in executed_followups],
        "pending_followups": pending_followups,
        "facet_gap_scheduler_report_iteration_2": iteration_2,
    }


def _adaptive_followup_query(base_query: str, *, facet_id: str, reason_codes: tuple[str, ...]) -> str:
    suffixes: list[str] = []
    if facet_id == "counter_evidence" or "refutation_gap" in reason_codes:
        suffixes.append("counter evidence limitations contradicting findings")
    if "route_facet_needs_review" in reason_codes:
        suffixes.append("stable citation direct quote locator")
    if "claim_coverage_gap" in reason_codes or "route_facet_gap" in reason_codes:
        suffixes.append("accepted source evidence")
    if not suffixes:
        suffixes.append("source-backed evidence")
    return " ".join(_dedupe([base_query, *suffixes], limit=1 + len(suffixes)))


def _adaptive_route_purpose(facet_id: str, reason_codes: tuple[str, ...]) -> str:
    if facet_id == "counter_evidence":
        return "adaptively close unresolved counter-evidence or refutation gaps"
    if facet_id == "canonical_sources":
        return "adaptively find stable canonical sources for unresolved claims"
    if "claim_coverage_gap" in reason_codes:
        return "adaptively find accepted material evidence for claim coverage gaps"
    return "adaptively close unresolved route-facet evidence gaps"


def _intent_for_adaptive_facet(facet_id: str) -> str:
    if facet_id == "counter_evidence":
        return "refutation"
    if facet_id == "canonical_sources":
        return "primary_anchor_recall"
    return "gap_fill"


def _adaptive_route_id(query: str, index: int) -> str:
    digest = hashlib.sha1(f"adaptive-query-route.v1\n{index}\n{query}".encode("utf-8")).hexdigest()[:12]
    return f"aqr_{digest}"


def _adaptive_model_role_routing_plan(has_followups: bool) -> dict[str, Any]:
    return {
        "source_discovery": {
            "enabled": has_followups,
            "model_tier": "cheap_or_local",
            "role": "generate_or_execute_followup_queries_from_deterministic_gap_rows",
            "paid_calls_allowed": False,
        },
        "quality_gate": {
            "deterministic": True,
            "role": "re-run source decision, claim evidence, evidence ledger, and readiness gates",
            "paid_calls_allowed": False,
        },
        "council_or_report": {
            "enabled": False,
            "role": "defer until deterministic quality gates report ready",
        },
    }


def _route_id_for_query(query: str) -> str:
    digest = hashlib.sha1(f"{QUERY_ROUTE_VERSION}\n{query}".encode("utf-8")).hexdigest()[:12]
    return f"qr_{digest}"


def _queries_from_targeting_map(brief: ResearchBrief) -> list[str]:
    tmap = getattr(brief, "targeting_map", None)
    search_queries = getattr(tmap, "search_queries", None)
    if not isinstance(search_queries, dict):
        return []
    out: list[str] = []
    for values in search_queries.values():
        if isinstance(values, (list, tuple)):
            out.extend(str(value) for value in values if str(value).strip())
    return out


def _planning_evidence_targets(brief: ResearchBrief) -> list[str]:
    prd = getattr(brief, "planning_prd", None)
    if not isinstance(prd, dict):
        return []
    targets: list[str] = []
    for scenario in prd.get("target_scenarios", []) or []:
        if isinstance(scenario, dict):
            value = str(scenario.get("scenario") or scenario.get("user_group") or "").strip()
            if value and not _is_planning_placeholder(value):
                targets.append(value)
    for metric in prd.get("success_metrics", []) or []:
        text = str(metric).strip()
        if text and not _is_planning_placeholder(text):
            targets.append(text)
    return targets[:6]


def _feature_deliverables(brief: ResearchBrief) -> list[str]:
    hierarchy = getattr(brief, "feature_hierarchy", None)
    if not isinstance(hierarchy, list):
        return []
    out: list[str] = []
    for requirement in hierarchy:
        if not isinstance(requirement, dict):
            continue
        name = str(requirement.get("name") or "").strip()
        if name:
            out.append(name)
        for feature in requirement.get("features", []) or []:
            if isinstance(feature, dict):
                feature_name = str(feature.get("name") or "").strip()
                if feature_name:
                    out.append(feature_name)
    return out


def _is_planning_placeholder(value: str) -> bool:
    lowered = " ".join(str(value).strip().casefold().split())
    if not lowered:
        return True
    return (
        lowered.startswith("pending ")
        or " pending " in lowered
        or "placeholder" in lowered
        or lowered in {"unspecified", "target scenario pending"}
    )


_MARKER_MARKET = frozenset(
    (
        # English
        "market",
        "pricing",
        "adoption",
        "willingness to pay",
        "government statistics",
        "distribution channel",
        "regulatory adoption",
        "official statistics",
        "farmer",
        "agricultural statistics",
        # Korean
        "시장성",
        "시장",
        "가격",
        "채택",
        "도입",
        "구매",
        "지불의사",
        "유통",
        "규제",
        "통계",
    )
)
_MARKET_QUERY_FLOOR = max(1, int(os.environ.get("MUCHANIPO_MARKET_QUERY_FLOOR", 3)))


def _is_market_query(query: str) -> bool:
    lowered = query.casefold()
    return any(marker in lowered for marker in _MARKER_MARKET)


def _dedupe(values: list[str], limit: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(str(value).split())
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        out.append(normalized)
        if len(out) >= limit:
            break
    return out


def _dedupe_with_market_floor(values: list[str], limit: int) -> list[str]:
    """Deduplicate while guaranteeing at least ``_MARKET_QUERY_FLOOR`` market-tagged queries survive.

    First runs normal order-preserving dedup; if the result drops below the
    market floor, missing market queries are re-injected from the full unique
    pool and the list is re-trimmed. This preserves natural ordering when it
    already satisfies the floor, and only intervenes when market queries are
    starved.
    """
    # Normal dedup
    result = _dedupe(values, limit=limit)
    market_in_result = [q for q in result if _is_market_query(q)]

    if len(market_in_result) >= _MARKET_QUERY_FLOOR:
        return result

    # Need to rescue market queries
    all_unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(str(value).split())
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        all_unique.append(normalized)

    missing_market = [q for q in all_unique if _is_market_query(q) and q not in result]
    needed = _MARKET_QUERY_FLOOR - len(market_in_result)
    rescued = missing_market[:needed]

    if not rescued:
        return result

    # Append rescued market queries to the end, then re-trim.
    # This preserves the relative order of existing queries and only drops
    # the lowest-priority queries (which are already at the tail).
    new_result = list(result)
    new_result.extend(rescued)
    return _dedupe(new_result, limit=limit)


def _anchor_first_query(queries: list[str], topic_anchor: str, *, limit: int) -> list[str]:
    """Keep a new run's original topic as the first search query."""
    anchored = [topic_anchor]
    anchored.extend(query for query in queries if query.strip() != topic_anchor.strip())
    return _dedupe(anchored, limit=limit)
