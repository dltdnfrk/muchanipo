"""Query helpers for AutoResearch.

The goal is to keep Stage 3 from becoming a vague "search the web" step.
Each query expansion states a distinct evidence intent so runners can collect
coverage across primary evidence, constraints, and counter-signals.
"""
from __future__ import annotations

import re


def expand_query(
    query: str,
    *,
    context: str = "",
    quality_bar: str = "",
    max_queries: int = 5,
) -> list[str]:
    query = query.strip()
    if not query:
        return []

    bridge_query = _english_bridge_query(query, context=context)
    candidates = [
        query,
        bridge_query,
        f"{query} official statistics peer reviewed evidence",
        f"{query} adoption constraints pricing risk",
        f"{query} counter evidence limitations failure cases",
    ]
    if bridge_query:
        candidates.extend(
            [
                f"{bridge_query} peer reviewed evidence",
                f"{bridge_query} market adoption pricing distribution",
            ]
        )
    if context.strip():
        candidates.append(f"{query} {context.strip()} source evidence")
    if quality_bar.strip():
        candidates.append(f"{query} {quality_bar.strip()} source quality")

    out: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = " ".join(candidate.split())
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        out.append(normalized)
        if len(out) >= max(1, max_queries):
            break
    return out


def _english_bridge_query(query: str, *, context: str = "") -> str:
    """Add a deterministic English bridge for Korean AgTech/diagnostics topics.

    Academic APIs often retrieve richer metadata for English biomedical and
    agriculture terms than for Korean product-language phrasing. This is not a
    translation engine; it only expands high-signal domain terms so a Korean
    user query still reaches the live evidence path.
    """
    text = f"{query} {context}".lower()
    if not re.search(r"[가-힣]", text):
        return ""

    terms: list[str] = []
    keyword_map = [
        (("딸기", "strawberry"), "strawberry"),
        (("농가", "농업", "작목반", "농협"), "farmers agriculture"),
        (("저비용", "저가", "비용", "가격", "지불"), "low cost pricing willingness to pay"),
        (("분자진단", "pcr", "lamp", "진단키트", "진단 키트"), "molecular diagnostic kit plant disease detection"),
        (("병해충", "병원체", "감염", "바이러스", "균"), "plant pathogen disease diagnostics"),
        (("시장성", "구매", "수요", "유통", "실증"), "market adoption distribution field validation"),
        (("한국", "국내"), "Korea"),
    ]
    for needles, phrase in keyword_map:
        if any(needle in text for needle in needles):
            terms.append(phrase)

    if not terms:
        return ""
    return " ".join(dict.fromkeys(" ".join(terms).split()))
