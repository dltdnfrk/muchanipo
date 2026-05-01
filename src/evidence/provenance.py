"""Provenance helpers for evidence artifacts."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Provenance:
    kind: str
    captured_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict = field(default_factory=dict)
    # Structured fields for source traceability (Council requirement: DOI, grade,
    # journal, institution must be first-class so consumers can distinguish real
    # papers from LLM hallucinations without guessing dict keys.)
    doi: str | None = None
    journal: str | None = None
    institution: str | None = None
    retrieved_at: str | None = None

    def as_dict(self) -> dict:
        result: dict[str, object] = {
            "kind": self.kind,
            "captured_at": self.captured_at,
            **self.metadata,
        }
        if self.doi is not None:
            result["doi"] = self.doi
        if self.journal is not None:
            result["journal"] = self.journal
        if self.institution is not None:
            result["institution"] = self.institution
        if self.retrieved_at is not None:
            result["retrieved_at"] = self.retrieved_at
        return result
