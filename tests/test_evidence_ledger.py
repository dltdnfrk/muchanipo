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
    verification_status: str | None = None,
) -> EvidenceRef:
    provenance = {
        "kind": kind,
        "source_role": source_role,
        "authority_level": authority_level,
        "accepted": accepted,
        "metadata": {"source_text": quote or "", "locator": url or ""},
    }
    if verification_status:
        provenance["metadata"]["verification_status"] = verification_status
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
    direct_edge = payload["claim_entries"][0]["support_edges"][0]
    assert payload["claim_entries"][0]["claim_type"] == "source_says"
    assert direct_edge["support_type"] == "accepted_direct"
    assert direct_edge["verification_status"] == "directly_supports_claim"
    assert direct_edge["claim_type"] == "source_says"
    assert direct_edge["url_verified"] is True
    assert direct_edge["passage_found"] is True
    assert direct_edge["directly_supports_claim"] is True
    assert direct_edge["weak_support"] is False
    assert payload["metrics"]["claim_type.source_says_count"] == 1.0
    assert payload["metrics"]["claim_type.inferred_from_source_count"] == 0.0
    assert payload["metrics"]["citation.direct_support_count"] == 1.0
    assert payload["metrics"]["citation.weak_support_count"] == 0.0
    assert payload["metrics"]["citation.direct_support_rate"] == 0.333


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
    assert edge.verification_status == "passage_found"
    assert edge.claim_type == "unsupported"
    assert edge.url_verified is True
    assert edge.passage_found is True
    assert edge.directly_supports_claim is False
    assert edge.weak_support is False
    assert report.metrics["material_claim_support_coverage"] == 0.0
    assert report.metrics["citation.not_found_count"] == 0.0
    assert report.readiness == "needs_review"


def test_metadata_only_publication_date_claim_is_not_material_support() -> None:
    report = build_evidence_ledger_report(
        [
            Finding(
                claim="Published at 2025-01-01.",
                support=[
                    _ref(
                        "published-date",
                        title="Field validation study",
                        quote="Published at 2025-01-01.",
                    )
                ],
                confidence=0.9,
            )
        ]
    )

    claim = report.claim_entries[0]
    edge = claim.support_edges[0]
    assert claim.claim_role == "background"
    assert edge.supported is False
    assert edge.support_type == "non_material"
    assert edge.directly_supports_claim is False
    assert report.metrics["material_claim_support_coverage"] == 0.0


def test_weak_source_passage_is_typed_as_inference_not_direct_support() -> None:
    report = build_evidence_ledger_report(
        [
            Finding(
                claim="The payment system uses token bucket rate limiting for authenticated requests.",
                support=[
                    _ref(
                        "partial-doc",
                        title="Rate limiting architecture note",
                        quote="Payment gateway controls traffic.",
                        verification_status="weak_support",
                    )
                ],
                confidence=0.82,
            )
        ]
    )

    claim = report.claim_entries[0]
    edge = claim.support_edges[0]
    assert edge.supported is False
    assert edge.verification_status == "weak_support"
    assert edge.claim_type == "inferred_from_source"
    assert edge.weak_support is True
    assert edge.directly_supports_claim is False
    assert claim.to_dict()["claim_type"] == "inferred_from_source"
    assert report.metrics["claim_type.inferred_from_source_count"] == 1.0
    assert report.metrics["citation.weak_support_count"] == 1.0
    assert report.metrics["citation.direct_support_rate"] == 0.0
    assert report.readiness == "needs_review"


def test_expected_claim_traceability_gap_marks_readiness_needs_review() -> None:
    expected = (
        ExpectedClaim(
            id="workflow-fidelity-gap",
            text="field validation sensitivity specificity evidence",
            required_terms=("field", "validation", "sensitivity", "specificity"),
            min_matched_terms=4,
        ),
    )

    report = build_evidence_ledger_report(
        [
            Finding(
                claim="The source supports a different market adoption claim.",
                support=[
                    _ref(
                        "different-claim",
                        title="Market adoption report",
                        quote="The source supports a different market adoption claim.",
                    )
                ],
                confidence=0.8,
            )
        ],
        expected_claims=expected,
    )

    assert report.expected_claim_traceability["workflow-fidelity-gap"]["supported"] is False
    assert report.metrics["expected_claim_traceability_score"] == 0.0
    assert report.metrics["expected_claim_gap_count"] == 1.0
    assert report.readiness == "needs_review"


def test_missing_locator_or_passage_is_not_found_and_never_supports_claim() -> None:
    report = build_evidence_ledger_report(
        [
            Finding(
                claim="A material claim needs a locator and a passage.",
                support=[
                    _ref(
                        "missing-locator",
                        title="Unlocatable evidence",
                        quote="A material claim needs a locator and a passage.",
                        url=None,
                    ),
                    _ref(
                        "missing-passage",
                        title="Locator without passage",
                        quote=None,
                        url="https://example.com/evidence",
                    ),
                ],
                confidence=0.9,
            )
        ]
    )

    by_source = {edge.source_id: edge for edge in report.claim_entries[0].support_edges}
    assert by_source["missing-locator"].verification_status == "not_found"
    assert by_source["missing-locator"].url_verified is False
    assert by_source["missing-locator"].passage_found is True
    assert by_source["missing-passage"].verification_status == "url_verified"
    assert by_source["missing-passage"].url_verified is True
    assert by_source["missing-passage"].passage_found is False
    assert all(edge.supported is False for edge in by_source.values())
    assert report.metrics["citation.not_found_count"] == 1.0
    assert report.metrics["citation.url_verified_count"] == 1.0


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


def test_contradicting_evidence_is_disclosed_as_readiness_impact_event() -> None:
    report = build_evidence_ledger_report(
        [
            Finding(
                claim="Market adoption is already proven in regulated hospitals.",
                support=[
                    _ref(
                        "direct-support",
                        title="Hospital adoption survey",
                        quote="Market adoption is already proven in regulated hospitals.",
                    ),
                    _ref(
                        "contradictory-source",
                        title="Hospital procurement contradiction study",
                        quote="Hospital procurement evidence contradicts the adoption claim and reports unresolved barriers.",
                        verification_status="contradiction",
                    ),
                ],
                confidence=0.88,
            )
        ]
    )

    payload = report.to_dict()
    claim = payload["claim_entries"][0]
    contradiction_edge = next(edge for edge in claim["support_edges"] if edge["source_id"] == "contradictory-source")
    assert contradiction_edge["contradiction"] is True
    assert contradiction_edge["supported"] is False
    assert contradiction_edge["verification_status"] == "contradiction"
    assert payload["metrics"]["citation.contradiction_count"] == 1.0
    assert payload["metrics"]["material_contradiction_count"] == 1.0
    assert payload["metrics"]["material_contradiction_disclosure_rate"] == 1.0
    assert payload["readiness"] == "needs_review"
    contradiction_events = [
        event for event in payload["quality_gate_events"] if event.get("status") == "contradiction_disclosure_built"
    ]
    assert contradiction_events
    assert contradiction_events[0]["contradictions"] == [
        {
            "claim_id": "claim-001",
            "claim": "Market adoption is already proven in regulated hospitals.",
            "source_ids": ["contradictory-source"],
            "readiness_impact": "needs_review",
            "disclosure": "material claim has unresolved contradictory evidence",
        }
    ]


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
