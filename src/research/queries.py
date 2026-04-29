"""Query helpers for AutoResearch.

The goal is to keep Stage 3 from becoming a vague "search the web" step.
Each query expansion states a distinct evidence intent so runners can collect
coverage across primary evidence, constraints, and counter-signals.
"""
from __future__ import annotations


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

    candidates = [
        query,
        f"{query} official statistics peer reviewed evidence",
        f"{query} adoption constraints pricing risk",
        f"{query} counter evidence limitations failure cases",
    ]
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
