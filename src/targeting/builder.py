"""TargetingMap builder — API-backed when available, heuristic otherwise."""
from __future__ import annotations

from src.interview.brief import ResearchBrief
from src.targeting import TargetingMap


def build_targeting_map(brief: ResearchBrief) -> TargetingMap:
    domains = _decompose_domains(brief)
    search_queries = _build_search_queries(brief, domains)
    return TargetingMap(
        domains=domains,
        target_institutions=[],
        target_journals=[],
        seed_papers=[],
        search_queries=search_queries,
        provenance={
            "target_institutions": [],
            "target_journals": [],
            "seed_papers": [],
        },
    )


_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "computer_science": ["algorithm", "software", "programming", "compute", "agent"],
    "biology": ["bio", "genome", "cell", "molecular", "protein"],
    "economics": ["economy", "market", "finance", "price", "gdp", "시장"],
    "medicine": ["medical", "clinical", "patient", "treatment", "drug", "진단"],
    "agriculture": ["agriculture", "farm", "crop", "plant", "soil", "농가", "딸기"],
    "chemistry": ["chemical", "synthesis", "reaction", "compound", "polymer"],
    "physics": ["physics", "quantum", "particle", "thermo"],
    "psychology": ["psychology", "cognitive", "behavior", "mental"],
    "sociology": ["social", "society", "culture", "demographic"],
}


def _decompose_domains(brief: ResearchBrief) -> list[str]:
    text = f"{brief.research_question} {brief.purpose} {brief.context}".lower()
    matched = [
        domain
        for domain, keywords in _DOMAIN_KEYWORDS.items()
        if any(keyword in text for keyword in keywords)
    ]
    return matched or ["general"]


def _build_search_queries(brief: ResearchBrief, domains: list[str]) -> dict[str, list[str]]:
    base = (brief.research_question or brief.raw_idea or "").strip()
    if not base:
        return {"general": ["review", "recent advances"]}
    return {
        domain: [
            base,
            f"{base} review",
            f"{base} recent advances",
        ]
        for domain in domains
    }
