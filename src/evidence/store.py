"""In-memory evidence store wired to citation_grounder provenance check."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse
from collections import Counter

from .artifact import EvidenceRef
from src.runtime.live_mode import LiveModeViolation


_ACADEMIC_KINDS = {
    "openalex",
    "crossref",
    "semantic_scholar",
    "unpaywall",
    "arxiv",
    "core",
}
_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
_CONTENT_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[가-힣]{2,}", re.UNICODE)


def _validate_provenance(refs: list[EvidenceRef], *, require_live: bool = False) -> dict[str, bool]:
    """Per-evidence provenance flags.

    The optional citation_grounder/lockdown validator is useful but not the
    only gate. Stage-4 source-grounding must still fail closed enough when that
    optional integration is absent or permissive, so every ref also passes a
    stdlib structural check.
    """
    if not refs:
        return {}
    structural_flags = {
        ref.id: _structural_provenance_ok(ref)
        for ref in refs
    }
    try:
        from src.eval.citation_grounder import _lockdown_validate_provenance
    except Exception as exc:  # noqa: BLE001
        if require_live:
            raise LiveModeViolation("live mode requires provenance validator availability") from exc
        return structural_flags

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
        lockdown_flags = _lockdown_validate_provenance(payload)
    except Exception as exc:  # noqa: BLE001
        if require_live:
            raise LiveModeViolation("live mode provenance validation failed") from exc
        lockdown_flags = {ref.id: True for ref in refs}
    combined: dict[str, bool] = {}
    for ref in refs:
        source_text = (ref.provenance or {}).get("source_text")
        structural_ok = bool(structural_flags.get(ref.id, False))
        # Academic clients keep source_text as structured metadata. The
        # stdlib structural check understands that shape; lockdown's exact
        # substring rule only understands plain source text and would reject
        # valid metadata-derived quotes.
        if source_text is not None and not isinstance(source_text, str):
            combined[ref.id] = structural_ok
        else:
            combined[ref.id] = bool(lockdown_flags.get(ref.id, True)) and structural_ok
    return combined


def _structural_provenance_ok(ref: EvidenceRef) -> bool:
    prov = ref.provenance or {}
    quote = str(ref.quote or "").strip()
    source_text = _source_text_as_text(prov.get("source_text"))
    if not quote or not source_text:
        return False
    if quote not in source_text and _token_coverage(quote, source_text) < 0.8:
        return False

    source = str(ref.source_url or prov.get("source") or "").strip()
    if source and not _valid_source_locator(source):
        return False

    doi = _normalize_doi(str(prov.get("doi") or "")) or _doi_from_locator(source)
    if prov.get("doi") and not doi:
        return False

    kind = str(prov.get("kind") or "").strip().lower()
    if kind in _ACADEMIC_KINDS and str(ref.source_grade).upper() == "A" and not doi:
        return False
    return True


def _source_text_as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)


def _valid_source_locator(value: str) -> bool:
    if value.startswith(("doi:", "arxiv:", "pmid:")):
        return True
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _normalize_doi(value: str) -> str:
    doi = value.strip()
    if not doi:
        return ""
    lowered = doi.lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if lowered.startswith(prefix):
            doi = doi[len(prefix):]
            break
    return doi if _DOI_RE.match(doi) else ""


def _doi_from_locator(value: str) -> str:
    parsed = urlparse(value)
    if parsed.netloc.lower() == "doi.org":
        return _normalize_doi(parsed.path.lstrip("/"))
    if value.startswith("doi:"):
        return _normalize_doi(value)
    return ""


def _token_coverage(quote: str, source_text: str) -> float:
    tokens = {
        token.lower()
        for token in _CONTENT_TOKEN_RE.findall(quote)
        if len(token) >= 2
    }
    if not tokens:
        return 0.0
    source_tokens = {
        token.lower()
        for token in _CONTENT_TOKEN_RE.findall(source_text)
        if len(token) >= 2
    }
    return len(tokens & source_tokens) / len(tokens)


@dataclass
class EvidenceStore:
    require_live: bool = False
    _items: dict[str, EvidenceRef] = field(default_factory=dict)
    _provenance_flags: dict[str, bool] = field(default_factory=dict)

    def add(self, ref: EvidenceRef) -> EvidenceRef:
        ref.validate()
        flags = _validate_provenance([ref], require_live=self.require_live)
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
