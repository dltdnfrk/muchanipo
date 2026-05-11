from src.evidence.artifact import EvidenceRef, Finding
from src.report.claim_matrix import build_claim_evidence_matrix
from src.research.evidence_ledger import build_evidence_ledger_report
from src.research.source_decision_ledger import SourceDecision, SourceDecisionLedger


def _ref(source_id: str, *, quote: str = "assay detects target marker", role: str = "core_evidence") -> EvidenceRef:
    return EvidenceRef(
        id=source_id,
        source_url=f"https://doi.org/10.1000/{source_id}",
        source_title="Traceable assay validation study",
        quote=quote,
        source_grade="A",
        provenance={"kind": "paper", "source_role": role, "claim_role": "material"},
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
    assert row.canonical_ids == ("10.1000/accepted",)
    assert row.to_dict()["support_status"] == "supported"
    assert row.to_dict()["claim_type"] == "source_says"


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
    assert by_claim["assay detects target marker"].claim_type == "inferred"
    assert by_claim["uncited forecast conclusion"].status == "unsupported"
    assert by_claim["uncited forecast conclusion"].claim_type == "unsupported"
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
    assert "accepted_source_decision" in row.missing_requirements
    assert "canonical_identity" in row.missing_requirements
    assert "material_source_role" in row.missing_requirements


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
