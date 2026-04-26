"""Query helpers for AutoResearch."""
from __future__ import annotations


def expand_query(query: str) -> list[str]:
    query = query.strip()
    return [query] if query else []
