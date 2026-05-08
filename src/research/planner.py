"""ResearchBrief to ResearchPlan conversion."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

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


class ResearchPlanner:
    def plan(self, brief: ResearchBrief, *, max_queries: int = 8) -> ResearchPlan:
        topic_anchor = str(getattr(brief, "original_topic", "") or "").strip()
        query = topic_anchor or brief.research_question.strip() or brief.raw_idea.strip()
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
        )


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
