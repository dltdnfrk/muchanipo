"""Synthesis helpers for mock-first AutoResearch."""
from __future__ import annotations

from src.evidence.artifact import EvidenceRef, Finding


def finding_from_query(query: str, evidence: EvidenceRef) -> Finding:
    return Finding(
        claim=f"Initial research direction for: {query}",
        support=[evidence],
        confidence=0.6,
        limitations=["mock research runner; replace with real evidence collection"],
    )
