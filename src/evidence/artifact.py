"""Evidence artifacts shared by research, reports, and council."""
from __future__ import annotations

from dataclasses import dataclass, field

from .quality import validate_source_grade


@dataclass
class EvidenceRef:
    id: str
    source_url: str | None
    source_title: str | None
    quote: str | None
    source_grade: str
    provenance: dict

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if not self.id.strip():
            raise ValueError("EvidenceRef.id must not be empty")
        validate_source_grade(self.source_grade)


@dataclass
class Finding:
    claim: str
    support: list[EvidenceRef] = field(default_factory=list)
    confidence: float = 0.0
    limitations: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.claim.strip():
            raise ValueError("Finding.claim must not be empty")
