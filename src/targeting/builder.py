"""TargetingMap builder — API-backed, LLM-free."""

from __future__ import annotations

import os

from src.interview.brief import ResearchBrief
from src.research.academic import sync_search as academic_sync_search
from src.targeting import TargetingMap

# Wire-up placeholder for academic API modules (codex is building these).
# When the modules are available the imports will resolve automatically.
try:
    from src.research.academic.openalex import (
        query_institutions,
        query_journals,
        query_seed_papers,
    )
except Exception:  # pragma: no cover
    query_institutions = None  # type: ignore[assignment]
    query_journals = None  # type: ignore[assignment]
    query_seed_papers = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def build_targeting_map(brief: ResearchBrief) -> TargetingMap:
    """Build a ``TargetingMap`` from a ``ResearchBrief``.

    **CRITICAL SAFETY RULE**: ``target_institutions``, ``target_journals``,
    and ``seed_papers`` are filled **only** from academic API call results.
    LLM generation for these fields is strictly prohibited.
    """
    # Phase 1 — Domain decomposition (MECE, stdlib heuristic)
    domains = _decompose_domains(brief)

    # Phase 2-4 — API-backed lookups (graceful degradation if modules missing)
    institutions: list[str] = []
    journals: list[str] = []
    papers: list[str] = []
    provenance: dict[str, list[dict]] = {
        "target_institutions": [],
        "target_journals": [],
        "seed_papers": [],
    }

    if query_institutions is not None:
        try:
            inst_result = query_institutions(domains)
            if isinstance(inst_result, tuple) and len(inst_result) == 2:
                institutions, inst_prov = inst_result
                provenance["target_institutions"] = inst_prov
            elif isinstance(inst_result, list):
                institutions = inst_result
        except Exception:
            pass

    if query_journals is not None:
        try:
            jour_result = query_journals(domains)
            if isinstance(jour_result, tuple) and len(jour_result) == 2:
                journals, jour_prov = jour_result
                provenance["target_journals"] = jour_prov
            elif isinstance(jour_result, list):
                journals = jour_result
        except Exception:
            pass

    if query_seed_papers is not None:
        try:
            paper_result = query_seed_papers(domains)
            if isinstance(paper_result, tuple) and len(paper_result) == 2:
                papers, paper_prov = paper_result
                provenance["seed_papers"] = paper_prov
            elif isinstance(paper_result, list):
                papers = paper_result
        except Exception:
            pass
    if not papers and _live_academic_targeting_enabled():
        academic_papers, academic_prov = _query_multi_source_seed_papers(brief, limit=5)
        if academic_papers:
            papers = academic_papers
        provenance["seed_papers"].extend(academic_prov)

    # Phase 5 — Search query generation
    search_queries = _build_search_queries(brief, domains)

    return TargetingMap(
        domains=domains,
        target_institutions=institutions,
        target_journals=journals,
        seed_papers=papers,
        search_queries=search_queries,
        provenance=provenance,
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------
_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "computer_science": ["algorithm", "software", "programming", "compute"],
    "biology": ["bio", "genome", "cell", "molecular", "protein"],
    "economics": ["economy", "market", "finance", "price", "gdp"],
    "medicine": ["medical", "clinical", "patient", "treatment", "drug"],
    "agriculture": ["agriculture", "farm", "crop", "plant", "soil", "농업", "농가", "작물", "딸기", "과수", "스마트팜"],
    "chemistry": ["chemical", "synthesis", "reaction", "compound", "polymer"],
    "physics": ["physics", "quantum", "particle", "thermo"],
    "psychology": ["psychology", "cognitive", "behavior", "mental"],
    "sociology": ["social", "society", "culture", "demographic", "지역", "인구", "소비자"],
}


def _decompose_domains(brief: ResearchBrief) -> list[str]:
    """MECE-style domain decomposition using keyword heuristics."""
    text = f"{brief.research_question} {brief.purpose} {brief.context}".lower()
    matched: list[str] = []
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            matched.append(domain)
    if not matched:
        matched.append("general")
    return matched


def _build_search_queries(
    brief: ResearchBrief, domains: list[str]
) -> dict[str, list[str]]:
    """Generate per-domain search queries."""
    base = (brief.research_question or brief.raw_idea or "").strip()
    if not base:
        return {"general": ["review", "recent advances"]}

    queries: dict[str, list[str]] = {}
    for domain in domains:
        queries[domain] = [
            base,
            f"{base} review",
            f"{base} recent advances",
        ]
    return queries


def _live_academic_targeting_enabled() -> bool:
    return os.environ.get("MUCHANIPO_ACADEMIC_TARGETING", "").strip().lower() in {"1", "true", "yes", "on"}


def _query_multi_source_seed_papers(brief: ResearchBrief, *, limit: int) -> tuple[list[str], list[dict]]:
    query = (brief.research_question or brief.raw_idea or "").strip()
    if not query:
        return [], []
    try:
        refs = academic_sync_search.search(query, limit=limit)
    except Exception as exc:  # noqa: BLE001
        return [], [
            {
                "source": "academic_sync_search",
                "query": query,
                "status": "error",
                "error": str(exc).splitlines()[0][:160],
            }
        ]
    papers: list[str] = []
    provenance: list[dict] = []
    seen: set[str] = set()
    for ref in refs:
        prov = ref.provenance or {}
        paper = str(prov.get("doi") or ref.source_url or ref.source_title or ref.id).strip()
        if not paper or paper in seen:
            continue
        seen.add(paper)
        papers.append(paper)
        provenance.append(
            {
                "source": str(prov.get("kind") or "academic_sync_search"),
                "query": query,
                "status": "ok",
                "paper_id": ref.id,
                "doi": str(prov.get("doi") or ""),
                "title": ref.source_title or "",
            }
        )
        if len(papers) >= limit:
            break
    if not provenance:
        provenance.append(
            {
                "source": "academic_sync_search",
                "query": query,
                "status": "empty",
                "count": 0,
            }
        )
    return papers, provenance
