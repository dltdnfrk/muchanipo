from __future__ import annotations

import json

from src.evidence.artifact import EvidenceRef, Finding
from src.research.evidence_ledger import build_evidence_ledger_report
from src.research.max_plus_benchmark import ExpectedClaim, build_b1_probe_fixture, selected_max_plus_benchmark_fixture


def _ref(
    ref_id: str,
    *,
    title: str,
    quote: str | None,
    grade: str = "A",
    kind: str = "academic",
    url: str | None = "https://doi.org/10.1000/source",
    source_role: str = "primary",
    authority_level: str = "high",
    accepted: bool | None = True,
) -> EvidenceRef:
    provenance = {
        "kind": kind,
        "source_role": source_role,
        "authority_level": authority_level,
        "accepted": accepted,
        "metadata": {"source_text": quote or "", "locator": url or ""},
    }
    if accepted is False:
        provenance["rejection_reason"] = "source audit rejected this reference"
    return EvidenceRef(
        id=ref_id,
        source_url=url,
        source_title=title,
        quote=quote,
        source_grade=grade,
        provenance=provenance,
    )


def test_ledger_contract_is_json_serializable_and_scores_material_claim_support() -> None:
    primary = _ref(
        "doi-field",
        title="Field validation of pathogen assay",
        quote="Field validation reported assay sensitivity and specificity against culture-confirmed samples.",
    )
    background = _ref(
        "background-blog",
        title="Background explainer",
        quote="A background explainer mentions the assay market in passing.",
        grade="C",
        kind="web",
        source_role="background",
        authority_level="low",
    )
    unsupported = _ref(
        "rejected-catalog",
        title="Vendor catalog",
        quote="Catalog marketing copy claims broad use.",
        grade="D",
        kind="web",
        source_role="background",
        authority_level="low",
        accepted=False,
    )
    findings = [
        Finding(
            claim="The assay has field validation sensitivity and specificity evidence.",
            support=[primary],
            confidence=0.91,
        ),
        Finding(
            claim="Market adoption is proven by a vendor catalog.",
            support=[background, unsupported],
            confidence=0.86,
        ),
    ]

    report = build_evidence_ledger_report(findings)
    payload = report.to_dict()

    json.dumps(payload, ensure_ascii=False)
    assert payload["readiness"] == "needs_review"
    assert payload["metrics"]["material_claim_support_coverage"] == 0.5
    assert payload["metrics"]["background_leak_count"] == 2.0
    assert payload["metrics"]["unsupported_high_confidence_claim_count"] == 1.0
    assert [event["status"] for event in payload["quality_gate_events"]] == [
        "evidence_ledger_built",
        "claim_traceability_scored",
        "uncertainty_ledger_built",
    ]
    assert payload["claim_entries"][0]["support_edges"][0]["support_type"] == "accepted_direct"


def test_expected_claim_traceability_requires_one_accepted_support_edge_not_scattered_terms() -> None:
    expected = (
        ExpectedClaim(
            id="single-edge-required",
            text="Field validation sensitivity specificity evidence",
            required_terms=("field", "validation", "sensitivity", "specificity"),
            min_matched_terms=4,
        ),
    )
    scattered_findings = [
        Finding(
            claim="Field validation is mentioned in one source.",
            support=[_ref("field", title="Field note", quote="field validation only")],
            confidence=0.8,
        ),
        Finding(
            claim="Sensitivity and specificity are mentioned elsewhere.",
            support=[_ref("performance", title="Performance note", quote="sensitivity and specificity only")],
            confidence=0.8,
        ),
    ]

    scattered = build_evidence_ledger_report(scattered_findings, expected_claims=expected)

    assert scattered.metrics["expected_claim_traceability_score"] == 0.0
    assert scattered.expected_claim_traceability["single-edge-required"]["supported"] is False

    direct = build_evidence_ledger_report(
        [
            Finding(
                claim="Field validation sensitivity and specificity are reported together.",
                support=[
                    _ref(
                        "direct",
                        title="Field validation paper",
                        quote="The field validation reports sensitivity and specificity together.",
                    )
                ],
                confidence=0.8,
            )
        ],
        expected_claims=expected,
    )

    assert direct.metrics["expected_claim_traceability_score"] == 1.0
    assert direct.expected_claim_traceability["single-edge-required"]["support_edge_count"] == 1


def test_background_or_rejected_sources_cannot_support_material_claims() -> None:
    report = build_evidence_ledger_report(
        [
            Finding(
                claim="A material claim cannot be supported by background or rejected evidence.",
                support=[
                    _ref(
                        "background",
                        title="Background source",
                        quote="general background",
                        source_role="background",
                    ),
                    _ref(
                        "rejected",
                        title="Rejected source",
                        quote="rejected claim text",
                        accepted=False,
                    ),
                ],
                confidence=0.93,
            )
        ]
    )

    claim = report.claim_entries[0]
    assert all(edge.supported is False for edge in claim.support_edges)
    assert report.metrics["material_claim_support_coverage"] == 0.0
    assert report.metrics["unsupported_high_confidence_claim_count"] == 1.0


def test_fixture_only_b1_expected_claims_do_not_load_from_topic_text(monkeypatch) -> None:
    monkeypatch.delenv("MUCHANIPO_MAX_PLUS_BENCHMARK_ID", raising=False)
    assert selected_max_plus_benchmark_fixture() is None

    topic_accident = build_evidence_ledger_report(
        [
            Finding(
                claim="B-1 Erwinia amylovora iScience and STAR Protocols appear in a generic topic string.",
                support=[_ref("generic", title="Generic source", quote="Generic topic discussion only.")],
                confidence=0.4,
            )
        ]
    )

    assert topic_accident.expected_claim_traceability == {}
    assert topic_accident.metrics["expected_claim_traceability_score"] == 0.0

    fixture = build_b1_probe_fixture()
    fixture_report = build_evidence_ledger_report(
        [
            Finding(
                claim="The iScience and STAR Protocols anchors require a directly quoted support edge.",
                support=[
                    _ref(
                        "isci-star-anchor",
                        title="iScience and STAR Protocols anchor",
                        quote="iScience and STAR Protocols provide the directly quoted B-1 anchor evidence.",
                    )
                ],
                confidence=0.8,
            )
        ],
        expected_claims=fixture.expected_claims[:1],
    )

    assert set(fixture_report.expected_claim_traceability) == {fixture.expected_claims[0].id}


def test_off_topic_accepted_quote_cannot_support_material_claim() -> None:
    report = build_evidence_ledger_report(
        [
            Finding(
                claim="The payment system uses token bucket rate limiting for every authenticated request.",
                support=[
                    _ref(
                        "accepted-off-topic",
                        title="Compost moisture guide",
                        quote="Compost moisture improves when leaf litter is turned weekly.",
                    )
                ],
                confidence=0.92,
            )
        ]
    )

    edge = report.claim_entries[0].support_edges[0]
    assert edge.quote_overlap == 0.0
    assert edge.supported is False
    assert edge.support_type == "off_topic_quote"
    assert report.metrics["material_claim_support_coverage"] == 0.0
    assert report.readiness == "needs_review"


def test_expected_claim_traceability_requires_locator_and_accepted_support_semantics() -> None:
    expected = (
        ExpectedClaim(
            id="locator-required",
            text="field validation sensitivity specificity evidence",
            required_terms=("field", "validation", "sensitivity", "specificity"),
            min_matched_terms=4,
        ),
    )
    report = build_evidence_ledger_report(
        [
            Finding(
                claim="Field validation sensitivity and specificity are reported together.",
                support=[
                    _ref(
                        "quote-without-locator",
                        title="Field validation paper",
                        quote="The field validation reports sensitivity and specificity together.",
                        url=None,
                    )
                ],
                confidence=0.8,
            )
        ],
        expected_claims=expected,
    )

    trace = report.expected_claim_traceability["locator-required"]
    assert trace["supported"] is False
    assert trace["support_edge_count"] == 0
    assert report.metrics["expected_claim_traceability_score"] == 0.0


def test_expected_claim_traceability_rejects_background_and_rejected_expected_claim_sources() -> None:
    expected = (
        ExpectedClaim(
            id="accepted-direct-required",
            text="field validation sensitivity specificity evidence",
            required_terms=("field", "validation", "sensitivity", "specificity"),
            min_matched_terms=4,
        ),
    )
    report = build_evidence_ledger_report(
        [
            Finding(
                claim="Field validation sensitivity and specificity are reported together.",
                support=[
                    _ref(
                        "background-match",
                        title="Field validation background",
                        quote="The field validation reports sensitivity and specificity together.",
                        source_role="background",
                    ),
                    _ref(
                        "rejected-match",
                        title="Rejected field validation paper",
                        quote="The field validation reports sensitivity and specificity together.",
                        accepted=False,
                    ),
                ],
                confidence=0.8,
            )
        ],
        expected_claims=expected,
    )

    trace = report.expected_claim_traceability["accepted-direct-required"]
    assert trace["supported"] is False
    assert trace["support_edge_count"] == 0
    assert report.metrics["expected_claim_traceability_score"] == 0.0


def test_unresolved_conflict_blocks_research_readiness_until_reviewed() -> None:
    report = build_evidence_ledger_report(
        [
            Finding(
                claim="The payment system uses token bucket rate limiting for authenticated requests.",
                support=[
                    _ref(
                        "rate-limit-doc",
                        title="Token bucket rate limiting design",
                        quote="The payment system uses token bucket rate limiting for authenticated requests.",
                    )
                ],
                confidence=0.86,
            ),
            Finding(
                claim="There is a conflict between two deployment accounts.",
                support=[
                    _ref(
                        "deployment-conflict",
                        title="Deployment account conflict note",
                        quote="The deployment account evidence is conflicting and unresolved.",
                    )
                ],
                confidence=0.5,
                limitations=["Conflict remains unresolved between two deployment accounts."],
            ),
        ]
    )

    assert report.metrics["unresolved_conflict_count"] == 1.0
    assert report.metrics["unresolved_conflict_disclosure_rate"] == 1.0
    assert report.readiness == "needs_review"
