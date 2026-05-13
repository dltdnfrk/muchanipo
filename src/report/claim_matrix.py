"""Claim ↔ evidence matrix for strict source-grounded reports."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.evidence.artifact import EvidenceRef, Finding
from src.research.source_decision_ledger import SourceDecisionLedger


NON_SUPPORTING_VERIFICATION_STATUSES = {
    "weak_support",
    "passage_found",
    "url_verified",
    "not_found",
    "contradiction",
}


@dataclass(frozen=True)
class ClaimEvidenceRow:
    claim: str
    evidence_ids: tuple[str, ...]
    status: str
    reason: str
    confidence: float
    claim_type: str
    supporting_source_ids: tuple[str, ...] = ()
    canonical_ids: tuple[str, ...] = ()
    missing_requirements: tuple[str, ...] = ()
    citation_verification_statuses: tuple[str, ...] = ()
    direct_support_source_ids: tuple[str, ...] = ()
    weak_support_source_ids: tuple[str, ...] = ()
    contradicting_source_ids: tuple[str, ...] = ()
    not_found_source_ids: tuple[str, ...] = ()
    direct_support_source_count: int = 0
    required_direct_support_source_count: int = 1

    @property
    def support_status(self) -> str:
        return self.status

    @property
    def support_reason(self) -> str:
        return self.reason

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim,
            "evidence_ids": list(self.evidence_ids),
            "status": self.status,
            "claim_type": self.claim_type,
            "support_status": self.support_status,
            "reason": self.reason,
            "support_reason": self.support_reason,
            "confidence": self.confidence,
            "supporting_source_ids": list(self.supporting_source_ids),
            "canonical_ids": list(self.canonical_ids),
            "missing_requirements": list(self.missing_requirements),
            "citation_verification_statuses": list(self.citation_verification_statuses),
            "direct_support_source_ids": list(self.direct_support_source_ids),
            "weak_support_source_ids": list(self.weak_support_source_ids),
            "contradicting_source_ids": list(self.contradicting_source_ids),
            "not_found_source_ids": list(self.not_found_source_ids),
            "direct_support_source_count": self.direct_support_source_count,
            "required_direct_support_source_count": self.required_direct_support_source_count,
        }


@dataclass(frozen=True)
class ClaimEvidenceMatrix:
    rows: tuple[ClaimEvidenceRow, ...]

    @property
    def unsupported_count(self) -> int:
        return sum(1 for row in self.rows if row.status == "unsupported")

    @property
    def supported_count(self) -> int:
        return sum(1 for row in self.rows if row.status == "supported")

    @property
    def partial_count(self) -> int:
        return sum(1 for row in self.rows if row.status == "partial")

    @property
    def supported_ratio(self) -> float:
        if not self.rows:
            return 0.0
        return self.supported_count / len(self.rows)

    def to_dict(self) -> dict[str, Any]:
        rows = [row.to_dict() for row in self.rows]
        return {
            "row_count": len(self.rows),
            "supported_count": self.supported_count,
            "partial_count": self.partial_count,
            "unsupported_count": self.unsupported_count,
            "supported_ratio": round(self.supported_ratio, 3),
            "claim_type_counts": _count_values(row.claim_type for row in self.rows),
            "citation_verification_counts": _count_values(
                status for row in self.rows for status in row.citation_verification_statuses
            ),
            "rows": rows,
        }


def build_claim_evidence_matrix(
    findings: list[Finding],
    evidence_refs: list[EvidenceRef],
    *,
    accepted_evidence_ids: set[str] | None = None,
    source_decision_ledger: SourceDecisionLedger | None = None,
) -> ClaimEvidenceMatrix:
    """Build a conservative claim-to-citation matrix.

    A claim is `supported` only when it has at least one strict citation. When a
    SourceDecisionLedger is provided, its accepted/material/canonical-compatible
    decisions are the source of truth; needs-review, background, rejected, and
    off-topic decisions remain visible but cannot support material claims.
    """

    refs_by_id = {ref.id: ref for ref in evidence_refs}
    allowed_ids = set(accepted_evidence_ids) if accepted_evidence_ids is not None else None
    decisions_by_id = (
        {decision.source_id: decision for decision in source_decision_ledger.decisions}
        if source_decision_ledger is not None
        else {}
    )
    rows: list[ClaimEvidenceRow] = []
    for finding in findings:
        evidence_ids = tuple(ref.id for ref in finding.support if ref.id in refs_by_id)
        usable_ids = tuple(
            ref_id
            for ref_id in evidence_ids
            if _ref_can_support(refs_by_id[ref_id], allowed_ids, decisions_by_id)
        )
        canonical_ids = tuple(
            str(decisions_by_id[ref_id].canonical_id)
            for ref_id in usable_ids
            if ref_id in decisions_by_id and decisions_by_id[ref_id].canonical_id
        )
        missing_requirements = _missing_requirements(evidence_ids, refs_by_id, allowed_ids, decisions_by_id)
        verification = tuple(
            _citation_verification_status(refs_by_id[ref_id], allowed_ids, decisions_by_id)
            for ref_id in evidence_ids
        ) or ("not_found",)
        direct_support_ids = tuple(
            ref_id
            for ref_id, status in zip(evidence_ids, verification)
            if status == "directly_supports_claim"
        )
        weak_support_ids = tuple(
            ref_id
            for ref_id, status in zip(evidence_ids, verification)
            if status == "weak_support"
        )
        contradicting_ids = tuple(
            ref_id
            for ref_id, status in zip(evidence_ids, verification)
            if status == "contradiction"
        )
        not_found_ids = tuple(
            ref_id
            for ref_id, status in zip(evidence_ids, verification)
            if status == "not_found"
        )
        if usable_ids:
            status = "supported"
            reason = (
                "claim has at least one source-decision accepted strict citation"
                if decisions_by_id
                else "claim has at least one strict source citation"
            )
        elif evidence_ids:
            status = "partial"
            reason = "claim only has non-accepted or incomplete citations"
        else:
            status = "unsupported"
            reason = "claim has no citation"
        direct_support_count = len(direct_support_ids)
        required_direct_support_count = _required_direct_support_count_for_finding(finding)
        rows.append(
            ClaimEvidenceRow(
                claim=finding.claim,
                evidence_ids=usable_ids or evidence_ids,
                status=status,
                reason=reason,
                confidence=float(finding.confidence or 0.0),
                claim_type=_claim_type_for_status(status),
                supporting_source_ids=usable_ids,
                canonical_ids=canonical_ids,
                missing_requirements=missing_requirements,
                citation_verification_statuses=verification,
                direct_support_source_ids=direct_support_ids,
                weak_support_source_ids=weak_support_ids,
                contradicting_source_ids=contradicting_ids,
                not_found_source_ids=not_found_ids,
                direct_support_source_count=direct_support_count,
                required_direct_support_source_count=required_direct_support_count,
            )
        )
    return ClaimEvidenceMatrix(rows=tuple(rows))


def enforce_claim_evidence_gate(matrix: ClaimEvidenceMatrix, *, depth: str) -> dict[str, Any]:
    """Raise SourceAuditViolation when a strict depth has unsupported claims."""

    from src.research.karpathy_autoresearch import SourceAuditViolation

    normalized_depth = str(depth or "").casefold()
    strict = normalized_depth in {"max", "superdeep"}
    min_ratio = 1.0 if normalized_depth == "superdeep" else 0.85 if strict else 0.5
    passed = bool(matrix.rows) and matrix.unsupported_count == 0 and matrix.supported_ratio >= min_ratio
    if strict and matrix.unsupported_count:
        first = next(row for row in matrix.rows if row.status == "unsupported")
        raise SourceAuditViolation(f"unsupported claim blocked report: {first.claim[:160]}")
    if strict and matrix.supported_ratio < min_ratio:
        raise SourceAuditViolation(
            f"claim evidence gate failed: supported_ratio={matrix.supported_ratio:.2f} < {min_ratio:.2f}"
        )
    if strict:
        under_corroborated = next(
            (
                row
                for row in matrix.rows
                if row.status == "supported"
                and row.direct_support_source_count < row.required_direct_support_source_count
            ),
            None,
        )
        if under_corroborated is not None:
            raise SourceAuditViolation(
                "claim corroboration gate failed: "
                f"direct_support_source_count={under_corroborated.direct_support_source_count} < "
                f"required_direct_support_source_count={under_corroborated.required_direct_support_source_count} "
                f"for claim: {under_corroborated.claim[:160]}"
            )
    return {"passed": passed, **matrix.to_dict()}


def _required_direct_support_count_for_finding(finding: Finding) -> int:
    metadata = getattr(finding, "metadata", None) or {}
    explicit = metadata.get("min_corroboration") or metadata.get("required_direct_support_source_count")
    if explicit is not None:
        try:
            return max(1, int(explicit))
        except (TypeError, ValueError):
            return 1
    return 2 if float(finding.confidence or 0.0) >= 0.8 else 1


def _claim_type_for_status(status: str) -> str:
    normalized = str(status or "").casefold().strip()
    if normalized == "supported":
        return "source_says"
    if normalized == "partial":
        return "inferred_from_source"
    return "unsupported"


def _citation_verification_status(
    ref: EvidenceRef,
    allowed_ids: set[str] | None,
    decisions_by_id: dict[str, Any],
) -> str:
    if _ref_can_support(ref, allowed_ids, decisions_by_id):
        return "directly_supports_claim"
    explicit_status = _explicit_verification_status(ref)
    if explicit_status in NON_SUPPORTING_VERIFICATION_STATUSES:
        return explicit_status
    decision = decisions_by_id.get(ref.id)
    if decision is not None:
        if not bool(decision.locator_present):
            return "not_found"
        if not bool(decision.quote_present):
            return "url_verified"
        if bool(decision.accepted):
            return "weak_support"
        return "passage_found"
    if _has_quote(ref) and _has_locator(ref):
        if allowed_ids is None or ref.id in allowed_ids:
            return "weak_support"
        return "passage_found"
    if _has_locator(ref):
        return "url_verified"
    return "not_found"


def _ref_is_strict_source(ref: EvidenceRef) -> bool:
    provenance = ref.provenance or {}
    kind = str(provenance.get("kind") or "").strip().casefold()
    if kind in {"mock", "empty", "generated"}:
        return False
    if ref.id.startswith(("mock-", "empty-")):
        return False
    if str(ref.source_grade or "").upper() == "D":
        return False
    return bool(ref.source_url or ref.source_title or ref.quote)


def _has_locator(ref: EvidenceRef) -> bool:
    provenance = ref.provenance or {}
    metadata = provenance.get("metadata") if isinstance(provenance.get("metadata"), dict) else {}
    return bool(str(ref.source_url or provenance.get("source") or provenance.get("url") or metadata.get("locator") or "").strip())


def _has_quote(ref: EvidenceRef) -> bool:
    provenance = ref.provenance or {}
    metadata = provenance.get("metadata") if isinstance(provenance.get("metadata"), dict) else {}
    return bool(str(ref.quote or metadata.get("source_text") or "").strip())


def _explicit_verification_status(ref: EvidenceRef) -> str:
    provenance = ref.provenance or {}
    metadata = provenance.get("metadata") if isinstance(provenance.get("metadata"), dict) else {}
    return str(provenance.get("verification_status") or metadata.get("verification_status") or "").strip().casefold()


def _ref_can_support(
    ref: EvidenceRef,
    allowed_ids: set[str] | None,
    decisions_by_id: dict[str, Any],
) -> bool:
    if _explicit_verification_status(ref) in NON_SUPPORTING_VERIFICATION_STATUSES:
        return False
    decision = decisions_by_id.get(ref.id)
    if decision is not None:
        return (
            bool(decision.accepted)
            and decision.decision == "accepted"
            and decision.source_role in {"core_evidence", "comparison"}
            and bool(decision.quote_present)
            and bool(decision.locator_present)
            and "canonical_identity_unresolved" not in set(decision.rejection_codes)
        )
    return _ref_is_strict_source(ref) and (allowed_ids is None or ref.id in allowed_ids)


def _missing_requirements(
    evidence_ids: tuple[str, ...],
    refs_by_id: dict[str, EvidenceRef],
    allowed_ids: set[str] | None,
    decisions_by_id: dict[str, Any],
) -> tuple[str, ...]:
    missing: set[str] = set()
    if not evidence_ids:
        return ("citation",)
    for ref_id in evidence_ids:
        ref = refs_by_id[ref_id]
        decision = decisions_by_id.get(ref_id)
        if decision is not None:
            if not decision.accepted or decision.decision != "accepted":
                missing.add("accepted_source_decision")
            if decision.source_role not in {"core_evidence", "comparison"}:
                missing.add("material_source_role")
            if not decision.quote_present:
                missing.add("quote")
            if not decision.locator_present:
                missing.add("locator")
            if "canonical_identity_unresolved" in set(decision.rejection_codes):
                missing.add("canonical_identity")
        else:
            if not _ref_is_strict_source(ref):
                missing.add("strict_source")
            if allowed_ids is not None and ref_id not in allowed_ids:
                missing.add("accepted_source_id")
    return tuple(sorted(missing))


def _count_values(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return counts
