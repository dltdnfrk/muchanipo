"""Targeting Map — hallucination-resistant research targeting."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TargetingMap:
    """Research targeting metadata produced from a ResearchBrief."""

    domains: list[str]
    target_institutions: list[str]
    target_journals: list[str]
    seed_papers: list[str]
    search_queries: dict[str, list[str]]
    provenance: dict[str, list[dict]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "domains": self.domains,
            "target_institutions": self.target_institutions,
            "target_journals": self.target_journals,
            "seed_papers": self.seed_papers,
            "search_queries": self.search_queries,
            "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TargetingMap":
        return cls(
            domains=list(data.get("domains", [])),
            target_institutions=list(data.get("target_institutions", [])),
            target_journals=list(data.get("target_journals", [])),
            seed_papers=list(data.get("seed_papers", [])),
            search_queries=dict(data.get("search_queries", {})),
            provenance=dict(data.get("provenance", {})),
        )
