"""ResearchBrief to ResearchPlan conversion."""
from __future__ import annotations

from dataclasses import dataclass, field

from src.interview.brief import ResearchBrief
from .queries import expand_query


@dataclass
class ResearchPlan:
    brief_id: str
    queries: list[str]
    evidence_targets: list[str] = field(default_factory=list)
    expected_deliverables: list[str] = field(default_factory=list)
    stop_conditions: list[str] = field(default_factory=list)
    risk_notes: list[str] = field(default_factory=list)
    collection_rules: list[str] = field(default_factory=list)


class ResearchPlanner:
    def plan(self, brief: ResearchBrief, *, max_queries: int = 8) -> ResearchPlan:
        query = brief.research_question.strip() or brief.raw_idea.strip()
        queries = expand_query(
            query,
            context=brief.context,
            quality_bar=brief.quality_bar,
        ) or [query]
        targeting_queries = _queries_from_targeting_map(brief)
        queries = _dedupe(queries + targeting_queries, limit=max(1, max_queries))
        return ResearchPlan(
            brief_id=brief.id,
            queries=queries,
            evidence_targets=[brief.context] if brief.context else [],
            expected_deliverables=[brief.deliverable_type],
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
