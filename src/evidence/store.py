"""In-memory evidence store for mock-first pipeline tests."""
from __future__ import annotations

from dataclasses import dataclass, field

from .artifact import EvidenceRef


@dataclass
class EvidenceStore:
    _items: dict[str, EvidenceRef] = field(default_factory=dict)

    def add(self, ref: EvidenceRef) -> EvidenceRef:
        ref.validate()
        self._items[ref.id] = ref
        return ref

    def get(self, evidence_id: str) -> EvidenceRef | None:
        return self._items.get(evidence_id)

    def list(self) -> list[EvidenceRef]:
        return list(self._items.values())
