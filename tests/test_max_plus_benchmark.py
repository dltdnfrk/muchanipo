from __future__ import annotations

import json
from pathlib import Path

from src.evidence.artifact import EvidenceRef, Finding
from src.research.evidence_ledger import build_evidence_ledger_report
from src.research.karpathy_autoresearch import build_research_quality_audit
from src.research.planner import ResearchPlan
from src.research.max_plus_benchmark import (
    AHP_CRITICAL_MIN_SCORE,
    AHP_TARGET_SCORE,
    AutoresearchLogEntry,
    ExpectedClaim,
    append_autoresearch_log_entry,
    ahp_quality_gate_report,
    anchor_doi_coverage,
    benchmark_metrics,
    build_b1_probe_fixture,
    build_cross_domain_benchmark_matrix,
    build_quality_gate_event,
    claim_traceability_score,
    cross_domain_benchmark_metrics,
    evidence_quote_coverage,
    expected_claim_coverage,
    selected_max_plus_benchmark_fixture,
    source_authority_score,
    weak_source_penalty,
)


def _ref(
    ref_id: str,
    *,
    title: str,
    quote: str,
    grade: str = "A",
    kind: str = "academic",
    url: str = "https://doi.org/10.1000/strawberry-lamp",
    metadata: dict | None = None,
) -> EvidenceRef:
    return EvidenceRef(
        id=ref_id,
        source_url=url,
        source_title=title,
        quote=quote,
        source_grade=grade,
        provenance={"kind": kind, "metadata": {"source_text": quote, **(metadata or {})}},
    )


def _fixture_findings():
    fixture = build_b1_probe_fixture()
    findings = [
        Finding(
            claim=source.quote,
            support=[
                _ref(
                    source.id,
                    title=source.title,
                    quote=source.quote,
                    grade=source.source_grade,
                    kind=source.source_kind,
                    url=source.url,
                    metadata={"benchmark_id": fixture.benchmark_id},
                )
            ],
            confidence=0.9,
        )
        for source in fixture.source_backed_evidence
    ]
    return fixture, findings


def _useful_b1_report_text() -> str:
    return """
    The report distinguishes what the papers actually did, what is inferred from
    evidence, and what is proposed as AI acceleration. It covers public database
    URL, access, license, fields, and spectral sources. The local architecture
    includes table columns for compounds, spectra, bacterial targets, assay
    outcomes, and model features. It discloses gaps, uncertainty, failure modes,
    false positives, controls, and selectivity risks.
    """


def test_b1_probe_fixture_points_to_existing_max_report_without_requiring_paid_rerun() -> None:
    fixture = build_b1_probe_fixture(report_path=Path("/tmp/muchanipo-deep-research-max/report.md"))

    payload = fixture.to_dict()
    serialized_claims = json.dumps(payload["expected_claims"], ensure_ascii=False).casefold()

    assert payload["benchmark_id"] == "muchanipo-deep-research-max-plus-b1"
    assert payload["reference_report"]["path"] == "/tmp/muchanipo-deep-research-max/report.md"
    assert payload["reference_report"]["must_not_call_paid_max_again"] is True
    assert payload["probe"] == "B-1"
    assert "strawberry" not in serialized_claims
    assert "korea" not in serialized_claims
    assert {claim.id for claim in fixture.expected_claims} >= {
        "b1-isci-anchor-probe",
        "b1-xpro-protocol-anchor",
        "b1-field-validation-performance",
    }
    assert payload["workflow_fidelity_facets"]
    assert payload["final_report_usefulness_facets"]


def test_max_plus_benchmark_fixture_selection_is_explicit(monkeypatch) -> None:
    monkeypatch.delenv("MUCHANIPO_MAX_PLUS_BENCHMARK_ID", raising=False)

    assert selected_max_plus_benchmark_fixture() is None

    monkeypatch.setenv("MUCHANIPO_MAX_PLUS_BENCHMARK_ID", "b1")

    fixture = selected_max_plus_benchmark_fixture()
    assert fixture is not None
    assert fixture.benchmark_id == "muchanipo-deep-research-max-plus-b1"


def test_source_scoring_primitives_reward_authoritative_traceable_quotes_and_penalize_weak_sources() -> None:
    doi_ref = _ref(
        "doi-lamp",
        title="Field validation of strawberry pathogen LAMP assay",
        quote="Field validation reported sensitivity and specificity for strawberry pathogen LAMP assays.",
    )
    blog_ref = _ref(
        "blog-market",
        title="Generic agtech blog",
        quote="A blog says farmers might buy kits someday.",
        grade="D",
        kind="web",
        url="https://example.test/blog",
    )
    findings = [
        Finding(
            claim="Strawberry pathogen LAMP assays need field validation sensitivity and specificity evidence.",
            support=[doi_ref],
            confidence=0.86,
        ),
        Finding(
            claim="Korean strawberry farms need adoption and pricing evidence before commercialization.",
            support=[blog_ref],
            confidence=0.4,
        ),
    ]
    expected = (
        ExpectedClaim(
            id="field-validation",
            text="Field validation sensitivity specificity for strawberry pathogen LAMP assays",
            required_terms=("field", "validation", "sensitivity", "specificity", "strawberry"),
        ),
        ExpectedClaim(
            id="korea-adoption",
            text="Korea strawberry farms adoption pricing commercialization evidence",
            required_terms=("korea", "strawberry", "adoption", "pricing"),
        ),
    )

    assert source_authority_score(doi_ref) > source_authority_score(blog_ref)
    assert weak_source_penalty([doi_ref, blog_ref]) > 0
    assert evidence_quote_coverage(findings) == 1.0
    assert claim_traceability_score(findings) > 0.5

    coverage = expected_claim_coverage(findings, expected)

    assert coverage.covered_count == 1
    assert coverage.recall == 0.5
    assert coverage.missing_claim_ids == ("korea-adoption",)

    metrics = benchmark_metrics(findings, build_b1_probe_fixture())
    assert "expected_claim_traceability_score" in metrics
    assert "citation_integrity_score" in metrics
    assert "background_leak_count" in metrics


def test_ahp_quality_gate_passes_with_fixture_sources_reference_report_and_observability_events() -> None:
    fixture, findings = _fixture_findings()
    report_text = _useful_b1_report_text()
    progress_events = [
        {"stage": "quality_gate", "status": "source_audit_gate"},
        {"stage": "quality_gate", "status": "source_decision_ledger_built"},
        {"stage": "quality_gate", "status": "claim_evidence_gate"},
        {"stage": "quality_gate", "status": "evidence_ledger_built"},
        {
            "stage": "quality_gate",
            "status": "max_plus_benchmark_scored",
            "research_backend_contract_version": "research-backend.v1",
        },
    ]

    report = ahp_quality_gate_report(
        findings,
        fixture=fixture,
        accepted_source_ids={ref.id for finding in findings for ref in finding.support},
        progress_events=progress_events,
        final_report_text=report_text,
        reference_report_text=report_text,
    )

    assert report["passed"] is True
    assert report["score"] >= AHP_TARGET_SCORE
    assert report["missing_anchor_dois"] == []
    assert set(report["covered_anchor_dois"]) == {
        "10.1016/j.isci.2023.106557",
        "10.1016/j.xpro.2023.102412",
    }
    assert all(score >= AHP_CRITICAL_MIN_SCORE for score in report["criterion_scores"].values())


def test_ahp_quality_gate_blocks_missing_required_anchor_doi() -> None:
    fixture, findings = _fixture_findings()
    isci_only = [
        finding
        for finding in findings
        if "xpro.2023.102412" not in " ".join(ref.source_url for ref in finding.support)
    ]

    anchor_coverage = anchor_doi_coverage(isci_only, fixture=fixture)
    report = ahp_quality_gate_report(
        isci_only,
        fixture=fixture,
        progress_events=[
            {"stage": "quality_gate", "status": "source_audit_gate"},
            {"stage": "quality_gate", "status": "source_decision_ledger_built"},
            {"stage": "quality_gate", "status": "claim_evidence_gate"},
            {"stage": "quality_gate", "status": "evidence_ledger_built"},
            {
                "stage": "quality_gate",
                "status": "max_plus_benchmark_scored",
                "research_backend_contract_version": "research-backend.v1",
            },
        ],
        final_report_text=_useful_b1_report_text(),
    )

    assert anchor_coverage["recall"] == 0.5
    assert report["passed"] is False
    assert report["missing_anchor_dois"] == ["10.1016/j.xpro.2023.102412"]
    assert any(gap.startswith("missing_anchor_doi:10.1016/j.xpro.2023.102412") for gap in report["top_gaps"])


def test_rq17d_offtopic_authority_sources_do_not_satisfy_b1_relevance_fixture() -> None:
    payload = json.loads(
        (Path(__file__).resolve().parent.parent / "benchmarks" / "deep_research_max_plus_b1_rq17d_offtopic_sources.json").read_text(
            encoding="utf-8"
        )
    )
    plan = ResearchPlan(
        brief_id="b1-rq17d-offtopic-regression",
        topic_anchor=payload["topic"],
        queries=[
            payload["topic"],
            "B-1 Erwinia amylovora fluorescent probe DOI field validation",
            "B-1 fire blight detection sample validation performance evidence",
        ],
    )
    refs = [
        _ref(
            item["id"],
            title=item["title"],
            quote=item["quote"],
            grade=item["grade"],
            kind=item["kind"],
            url=item["url"],
            metadata={"query": payload["topic"]},
        )
        for item in payload["sources"]
    ]
    findings = [
        Finding(claim=ref.source_title or ref.id, support=[ref], confidence=0.8)
        for ref in refs
    ]

    audit = build_research_quality_audit(findings, plan)
    accepted = [item for item in audit.source_evaluations if item.accepted]
    metrics = benchmark_metrics(findings, build_b1_probe_fixture())

    assert accepted == []
    assert len(audit.gaps) >= 1
    assert all(item.relevance_score < 1.0 for item in audit.source_evaluations)
    assert metrics["expected_claim_traceability_score"] == 0.0


def test_source_audit_allowlist_blocks_offtopic_sources_from_ledger_and_benchmark_metrics() -> None:
    fixture_payload = json.loads(
        (Path(__file__).resolve().parent.parent / "benchmarks" / "deep_research_max_plus_b1_rq17d_offtopic_sources.json").read_text(
            encoding="utf-8"
        )
    )
    fixture = build_b1_probe_fixture()
    expected = fixture.expected_claims[0]
    off_topic = fixture_payload["sources"][0]
    ref = _ref(
        off_topic["id"],
        title=off_topic["title"],
        quote=" ".join(expected.required_terms),
        grade=off_topic["grade"],
        kind=off_topic["kind"],
        url=off_topic["url"],
        metadata={"accepted": True, "query": fixture_payload["topic"]},
    )
    findings = [
        Finding(
            claim=expected.text,
            support=[ref],
            confidence=0.95,
        )
    ]

    baseline_ledger = build_evidence_ledger_report(findings, expected_claims=fixture.expected_claims)
    gated_ledger = build_evidence_ledger_report(
        findings,
        expected_claims=fixture.expected_claims,
        accepted_source_ids=set(),
        rejected_source_reasons={ref.id: "rejected: source text does not overlap with topic-specific plan terms"},
    )
    gated_metrics = benchmark_metrics(findings, fixture, accepted_source_ids=set())

    assert baseline_ledger.metrics["expected_claim_traceability_score"] > 0.0
    assert gated_ledger.source_entries[0].accepted is False
    assert "topic-specific" in gated_ledger.source_entries[0].rejection_reason
    assert gated_ledger.metrics["expected_claim_traceability_score"] == 0.0
    assert gated_ledger.metrics["material_claim_support_coverage"] == 0.0
    assert gated_ledger.metrics["quote_locator_coverage"] == 0.0
    assert gated_metrics["expected_claim_recall"] == 0.0
    assert gated_metrics["claim_traceability"] == 0.0
    assert gated_metrics["evidence_quote_coverage"] == 0.0
    assert gated_metrics["source_authority_score"] == 0.0


def test_benchmark_metrics_emits_citation_density_and_quant_claim_count() -> None:
    fixture = build_b1_probe_fixture()
    numeric_ref = _ref(
        "numeric-doi",
        title="B-1 detection validation",
        quote="B-1 detected Erwinia amylovora within 1 minute at 10 CFU/mL with 95% sensitivity.",
        url="https://doi.org/10.1016/j.isci.2023.106557",
    )
    qualitative_ref = _ref(
        "qualitative-doi",
        title="B-1 protocol",
        quote="The companion STAR Protocols article describes sample handling for B-1 fluorescence assays.",
        url="https://doi.org/10.1016/j.xpro.2023.102412",
    )
    findings = [
        Finding(
            claim="B-1 reports 95% sensitivity and a 10 CFU/mL detection limit for Erwinia amylovora.",
            support=[numeric_ref, qualitative_ref],
            confidence=0.9,
        ),
        Finding(
            claim="B-1 protocol evidence remains sample-handling focused.",
            support=[qualitative_ref],
            confidence=0.8,
        ),
    ]

    metrics = benchmark_metrics(findings, fixture)

    assert metrics["citation_density"] == 1.5
    assert metrics["quant_claim_count"] == 1.0


def test_cross_domain_benchmark_matrix_scores_generic_facet_source_and_claim_coverage() -> None:
    matrix = build_cross_domain_benchmark_matrix()

    assert matrix.benchmark_id == "muchanipo-deep-research-cross-domain-matrix-rq46"
    assert {case.domain_id for case in matrix.cases} == {
        "market_gtm",
        "policy_public_data",
        "finance_diligence",
        "legal_regulatory",
        "technical_product",
        "academic_literature",
        "local_business_ops",
        "scientific_hybrid",
    }
    serialized = json.dumps(matrix.to_dict(), ensure_ascii=False).casefold()
    assert "erwinia" not in serialized
    assert "10.1016/j.isci" not in serialized
    assert "b-1" not in serialized

    market_case = matrix.case_by_id("market_gtm")
    policy_case = matrix.case_by_id("policy_public_data")
    findings_by_case = {
        "market_gtm": [
            Finding(
                claim="A GTM benchmark should cite segment sizing, willingness-to-pay evidence, buyer personas, and channel constraints before recommending launch motion.",
                support=[
                    _ref(
                        "market-source",
                        title="Industry report with segment sizing and willingness-to-pay survey",
                        quote="Segment sizing, willingness-to-pay survey data, buyer personas, and channel constraints shape GTM launch decisions.",
                        grade="A",
                        kind="industry_report",
                        url="https://example.test/market-report",
                        metadata={"facet_id": "canonical_sources"},
                    )
                ],
                confidence=0.88,
            )
        ],
        "policy_public_data": [
            Finding(
                claim="A policy benchmark should connect official statistics, intervention outcomes, equity impact, and implementation constraints.",
                support=[
                    _ref(
                        "policy-source",
                        title="Government open data and policy evaluation",
                        quote="Official statistics and policy evaluation evidence describe intervention outcomes, equity impact, and implementation constraints.",
                        grade="A",
                        kind="government",
                        url="https://data.gov.example/policy-evaluation",
                        metadata={"facet_id": "counter_evidence"},
                    )
                ],
                confidence=0.86,
            )
        ],
    }

    metrics = cross_domain_benchmark_metrics(matrix, findings_by_case)

    assert market_case.expected_source_kinds == ("industry_report", "survey", "pricing_page")
    assert policy_case.expected_facets == ("background_scope", "canonical_sources", "counter_evidence")
    assert metrics["case_count"] == 8
    assert metrics["covered_case_count"] == 2
    assert metrics["domain_coverage"] == 0.25
    assert metrics["average_expected_claim_recall"] > 0.0
    assert metrics["average_source_authority_score"] > 0.0
    assert metrics["average_claim_traceability"] > 0.0
    assert metrics["b1_overfit_leak_count"] == 0
    assert metrics["facet_coverage"] >= 0.25


def test_autoresearch_log_entry_is_append_only_jsonl_with_decision_evidence(tmp_path: Path) -> None:
    log_path = tmp_path / "autoresearch-log.jsonl"
    entry = AutoresearchLogEntry(
        hypothesis="Authority-weighted quote coverage will expose Max report weak market claims.",
        code_test_change="Add benchmark metrics and regression coverage for quote-backed source scoring.",
        changed_files=("src/research/max_plus_benchmark.py", "tests/test_max_plus_benchmark.py"),
        metrics_before={"expected_claim_recall": 0.0},
        metrics_after={"expected_claim_recall": 0.67, "weak_source_penalty": 0.0},
        decision="keep",
        next_slice="Apply the same accepted-source gate to cross-domain benchmark cases.",
        evidence=("pytest tests/test_max_plus_benchmark.py",),
    )

    append_autoresearch_log_entry(log_path, entry)
    append_autoresearch_log_entry(
        log_path,
        AutoresearchLogEntry(
            hypothesis="A stricter weak-source penalty should be measured before UI exposure.",
            code_test_change="Prototype stricter weak-source penalty without accepting the behavior yet.",
            changed_files=("src/research/max_plus_benchmark.py",),
            metrics_before={"weak_source_penalty": 0.0},
            metrics_after={"weak_source_penalty": 0.25},
            decision="discard",
            next_slice="Revisit after source-role metadata is available in live findings.",
            evidence=("synthetic D-grade source regression",),
        ),
    )

    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]

    assert [row["decision"] for row in rows] == ["keep", "discard"]
    assert rows[0]["schema"] == "muchanipo.autoresearch_log.v1"
    assert rows[0]["hypothesis"]
    assert rows[0]["code_test_change"] == "Add benchmark metrics and regression coverage for quote-backed source scoring."
    assert rows[0]["changed_files"] == ["src/research/max_plus_benchmark.py", "tests/test_max_plus_benchmark.py"]
    assert rows[0]["next_slice"] == "Apply the same accepted-source gate to cross-domain benchmark cases."
    assert rows[0]["evidence"] == ["pytest tests/test_max_plus_benchmark.py"]


def test_quality_gate_event_exposes_benchmark_metrics_for_future_tauri_progress() -> None:
    event = build_quality_gate_event(
        benchmark_id="muchanipo-deep-research-max-plus-b1",
        metrics={
            "source_authority_score": 0.9,
            "weak_source_penalty": 0.0,
            "expected_claim_recall": 0.67,
            "evidence_quote_coverage": 1.0,
            "claim_traceability": 0.8,
        },
        decision="keep",
        hypothesis="Benchmark event contract is enough for RunProgress later.",
    )

    assert event == {
        "event": "research_progress",
        "stage": "quality_gate",
        "status": "max_plus_benchmark_scored",
        "research_backend_contract_version": "research-backend.v1",
        "benchmark_id": "muchanipo-deep-research-max-plus-b1",
        "decision": "keep",
        "hypothesis": "Benchmark event contract is enough for RunProgress later.",
        "metrics": {
            "source_authority_score": 0.9,
            "weak_source_penalty": 0.0,
            "expected_claim_recall": 0.67,
            "evidence_quote_coverage": 1.0,
            "claim_traceability": 0.8,
        },
    }
