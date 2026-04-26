"""Provenance helpers for evidence artifacts."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Provenance:
    kind: str
    captured_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"kind": self.kind, "captured_at": self.captured_at, **self.metadata}
