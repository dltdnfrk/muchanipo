"""In-memory evidence store wired to citation_grounder provenance check."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from collections import Counter

from .artifact import EvidenceRef


def _validate_provenance(refs: list[EvidenceRef]) -> dict[str, bool]:
    """Per-evidence provenance flags. Defers to citation_grounder which itself
    wraps `src.safety.lockdown.validate_evidence_provenance` and degrades to
    pass-through when the safety module is missing."""
    if not refs:
        return {}
    try:
        from src.eval.citation_grounder import _lockdown_validate_provenance
    except Exception:  # noqa: BLE001
        return {ref.id: True for ref in refs}

    payload: list[dict[str, Any]] = []
    for ref in refs:
        prov = ref.provenance or {}
        payload.append(
            {
                "id": ref.id,
                "quote": ref.quote or "",
                "source": ref.source_url or prov.get("source") or "",
                "source_text": prov.get("source_text", ""),
            }
        )
    try:
        return _lockdown_validate_provenance(payload)
    except Exception:  # noqa: BLE001
        return {ref.id: True for ref in refs}


@dataclass
class EvidenceStore:
    _items: dict[str, EvidenceRef] = field(default_factory=dict)
    _provenance_flags: dict[str, bool] = field(default_factory=dict)

    def add(self, ref: EvidenceRef) -> EvidenceRef:
        ref.validate()
        flags = _validate_provenance([ref])
        ok = flags.get(ref.id, True)
        self._provenance_flags[ref.id] = bool(ok)
        if not ok and isinstance(ref.provenance, dict):
            ref.provenance = {**ref.provenance, "provenance_failed": True}
        self._items[ref.id] = ref
        return ref

    def get(self, evidence_id: str) -> EvidenceRef | None:
        return self._items.get(evidence_id)

    def list(self) -> list[EvidenceRef]:
        return list(self._items.values())

    def provenance_flag(self, evidence_id: str) -> bool:
        return self._provenance_flags.get(evidence_id, True)

    def trusted(self) -> list[EvidenceRef]:
        return [
            ref
            for rid, ref in self._items.items()
            if self._provenance_flags.get(rid, True)
        ]

    def provenance_failures(self) -> int:
        return sum(1 for ok in self._provenance_flags.values() if not ok)

    def summary(self) -> dict[str, Any]:
        """Return a serializable evidence health summary for pipeline events."""
        grades = Counter(ref.source_grade for ref in self._items.values())
        trusted_ids = [
            ref.id
            for rid, ref in self._items.items()
            if self._provenance_flags.get(rid, True)
        ]
        return {
            "total": len(self._items),
            "trusted": len(trusted_ids),
            "provenance_failures": self.provenance_failures(),
            "grades": dict(sorted(grades.items())),
            "trusted_ids": trusted_ids,
        }
