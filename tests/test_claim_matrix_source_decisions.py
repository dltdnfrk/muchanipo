from __future__ import annotations

from src.evidence.artifact import EvidenceRef, Finding
import pytest

from src.report.claim_matrix import build_claim_evidence_matrix, enforce_claim_evidence_gate
from src.research.karpathy_autoresearch import SourceAuditViolation
from src.research.evidence_ledger import build_evidence_ledger_report
from src.research.source_decision_ledger import SourceDecision, SourceDecisionLedger


def _ref(
    source_id: str,
    *,
    quote: str = "assay detects target marker",
    role: str = "core_evidence",
    verification_status: str | None = None,
) -> EvidenceRef:
    provenance = {"kind": "paper", "source_role": role, "claim_role": "material"}
    if verification_status:
        provenance["metadata"] = {"verification_status": verification_status}
    return EvidenceRef(
        id=source_id,
        source_url=f"https://doi.org/10.1000/{source_id}",
        source_title="Traceable assay validation study",
        quote=quote,
        source_grade="A",
        provenance=provenance,
    )


def _decision(
    source_id: str,
    *,
    accepted: bool,
    decision: str = "accepted",
    role: str = "core_evidence",
    canonical_id: str | None = None,
    rejection_codes: tuple[str, ...] = (),
    quote_present: bool = True,
    locator_present: bool = True,
) -> SourceDecision:
    return SourceDecision(
        source_id=source_id,
        route_id="route-1",
        raw_title="Traceable assay validation study",
        raw_url=f"https://doi.org/10.1000/{source_id}",
        canonical_id=canonical_id,
        canonical_url=f"https://doi.org/{canonical_id}" if canonical_id else None,
        identifier_kind="doi" if canonical_id else "unknown",
        source_kind="paper",
        source_role=role,
        authority_level="high",
        accepted=accepted,
        decision=decision,
        relevance_score=0.95,
        reason="test decision",
        rejection_codes=rejection_codes,
        quote_present=quote_present,
        locator_present=locator_present,
        resolver_status="resolved" if canonical_id else "redirect_only",
    )


def test_claim_matrix_uses_source_decision_ledger_and_exposes_canonical_ids() -> None:
    accepted = _ref("accepted")
    blocked = _ref("blocked")
    background = _ref("background", role="background")
    findings = [Finding("assay detects target marker", [accepted, blocked, background], confidence=0.9)]
    ledger = SourceDecisionLedger(
        (
            _decision("accepted", accepted=True, canonical_id="10.1000/accepted"),
            _decision(
                "blocked",
                accepted=False,
                decision="needs_review",
                canonical_id=None,
                rejection_codes=("canonical_identity_unresolved",),
            ),
            _decision(
                "background",
                accepted=False,
                decision="rejected",
                role="background",
                canonical_id="10.1000/background",
                rejection_codes=("non_material_source_role",),
            ),
        )
    )

    matrix = build_claim_evidence_matrix(findings, [accepted, blocked, background], source_decision_ledger=ledger)

    row = matrix.rows[0]
    assert row.status == "supported"
    assert row.claim_type == "source_says"
    assert row.supporting_source_ids == ("accepted",)
    assert row.direct_support_source_ids == ("accepted",)
    assert row.weak_support_source_ids == ()
    assert row.not_found_source_ids == ()
    assert row.citation_verification_statuses == (
        "directly_supports_claim",
        "passage_found",
        "passage_found",
    )
    assert row.canonical_ids == ("10.1000/accepted",)
    assert row.to_dict()["support_status"] == "supported"
    assert row.to_dict()["claim_type"] == "source_says"
    assert row.to_dict()["citation_verification_statuses"] == [
        "directly_supports_claim",
        "passage_found",
        "passage_found",
    ]
    assert matrix.to_dict()["claim_type_counts"] == {"source_says": 1}
    assert matrix.to_dict()["citation_verification_counts"] == {
        "directly_supports_claim": 1,
        "passage_found": 2,
    }


def test_claim_matrix_classifies_partial_claims_as_inferred_and_uncited_claims_as_unsupported() -> None:
    blocked = _ref("blocked")
    uncited = Finding("uncited forecast conclusion", [], confidence=0.3)
    ledger = SourceDecisionLedger(
        (
            _decision(
                "blocked",
                accepted=False,
                decision="needs_review",
                rejection_codes=("canonical_identity_unresolved",),
            ),
        )
    )

    matrix = build_claim_evidence_matrix(
        [Finding("assay detects target marker", [blocked], confidence=0.7), uncited],
        [blocked],
        source_decision_ledger=ledger,
    )

    by_claim = {row.claim: row for row in matrix.rows}
    assert by_claim["assay detects target marker"].status == "partial"
    assert by_claim["assay detects target marker"].claim_type == "inferred_from_source"
    assert by_claim["assay detects target marker"].citation_verification_statuses == ("passage_found",)
    assert by_claim["assay detects target marker"].weak_support_source_ids == ()
    assert by_claim["uncited forecast conclusion"].status == "unsupported"
    assert by_claim["uncited forecast conclusion"].claim_type == "unsupported"
    assert by_claim["uncited forecast conclusion"].citation_verification_statuses == ("not_found",)
    assert by_claim["uncited forecast conclusion"].to_dict()["claim_type"] == "unsupported"


def test_claim_matrix_does_not_support_needs_review_or_background_decisions() -> None:
    blocked = _ref("blocked")
    background = _ref("background", role="background")
    findings = [Finding("assay detects target marker", [blocked, background], confidence=0.9)]
    ledger = SourceDecisionLedger(
        (
            _decision("blocked", accepted=False, decision="needs_review", rejection_codes=("canonical_identity_unresolved",)),
            _decision("background", accepted=False, decision="rejected", role="background", canonical_id="10.1000/background", rejection_codes=("non_material_source_role",)),
        )
    )

    matrix = build_claim_evidence_matrix(findings, [blocked, background], source_decision_ledger=ledger)

    row = matrix.rows[0]
    assert row.status == "partial"
    assert row.supporting_source_ids == ()
    assert row.direct_support_source_ids == ()
    assert row.weak_support_source_ids == ()
    assert row.citation_verification_statuses == ("passage_found", "passage_found")
    assert "accepted_source_decision" in row.missing_requirements
    assert "canonical_identity" in row.missing_requirements
    assert "material_source_role" in row.missing_requirements


def test_claim_matrix_honors_explicit_claim_source_verification_statuses() -> None:
    weak = _ref("weak", verification_status="weak_support")
    contradiction = _ref("contradiction", verification_status="contradiction")
    findings = [Finding("assay detects target marker", [weak, contradiction], confidence=0.9)]

    matrix = build_claim_evidence_matrix(findings, [weak, contradiction])

    row = matrix.rows[0]
    assert row.status == "partial"
    assert row.supporting_source_ids == ()
    assert row.direct_support_source_ids == ()
    assert row.weak_support_source_ids == ("weak",)
    assert row.contradicting_source_ids == ("contradiction",)
    assert row.citation_verification_statuses == ("weak_support", "contradiction")
    assert matrix.to_dict()["citation_verification_counts"] == {
        "weak_support": 1,
        "contradiction": 1,
    }


def test_strict_claim_gate_requires_per_claim_direct_corroboration_for_high_confidence_claims() -> None:
    primary = _ref("primary")
    secondary = _ref("secondary", verification_status="weak_support")
    findings = [Finding("high confidence market-size claim", [primary, secondary], confidence=0.91)]
    ledger = SourceDecisionLedger(
        (
            _decision("primary", accepted=True, canonical_id="10.1000/primary"),
            _decision("secondary", accepted=False, decision="needs_review", rejection_codes=("weak_support",)),
        )
    )

    matrix = build_claim_evidence_matrix(findings, [primary, secondary], source_decision_ledger=ledger)

    row = matrix.rows[0]
    assert row.status == "supported"
    assert row.direct_support_source_ids == ("primary",)
    with pytest.raises(SourceAuditViolation, match="claim corroboration gate failed"):
        enforce_claim_evidence_gate(matrix, depth="max")


def test_strict_claim_gate_passes_high_confidence_claim_with_two_direct_sources() -> None:
    primary = _ref("primary")
    secondary = _ref("secondary")
    findings = [Finding("high confidence market-size claim", [primary, secondary], confidence=0.91)]
    ledger = SourceDecisionLedger(
        (
            _decision("primary", accepted=True, canonical_id="10.1000/primary"),
            _decision("secondary", accepted=True, canonical_id="10.1000/secondary"),
        )
    )

    matrix = build_claim_evidence_matrix(findings, [primary, secondary], source_decision_ledger=ledger)
    gate = enforce_claim_evidence_gate(matrix, depth="max")

    row = matrix.rows[0]
    assert row.direct_support_source_ids == ("primary", "secondary")
    assert row.to_dict()["direct_support_source_count"] == 2
    assert row.to_dict()["required_direct_support_source_count"] == 2
    assert gate["passed"] is True


def test_evidence_ledger_preserves_source_decision_canonical_provenance() -> None:
    accepted = _ref("accepted")
    findings = [Finding("assay detects target marker", [accepted], confidence=0.9)]
    ledger = SourceDecisionLedger((_decision("accepted", accepted=True, canonical_id="10.1000/accepted"),))

    report = build_evidence_ledger_report(
        findings,
        accepted_source_ids=ledger.accepted_source_ids,
        source_decision_ledger=ledger,
    )

    source = report.source_entries[0].to_dict()
    edge = report.claim_entries[0].support_edges[0].to_dict()
    assert source["canonical_id"] == "10.1000/accepted"
    assert source["source_decision"] == "accepted"
    assert edge["canonical_id"] == "10.1000/accepted"
    assert edge["source_decision"] == "accepted"
