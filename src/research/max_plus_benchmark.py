"""Max-Plus benchmark contracts for source-grounded autoresearch.

This module does not call Gemini/Deep Research Max. It only records a local
reference report path and scores Muchanipo outputs against explicit,
source-grounded expectations.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from src.evidence.artifact import EvidenceRef, Finding
from src.research.evidence_ledger import build_evidence_ledger_report
from src.research.event_contract import RESEARCH_BACKEND_CONTRACT_VERSION


DEFAULT_MAX_REPORT_PATH = Path("/tmp/muchanipo-deep-research-max/report.md")
DEFAULT_MAX_PROMPT_PATH = Path("/tmp/muchanipo_deep_research_prompt.txt")
DEFAULT_MAX_RESPONSE_PATH = Path("/tmp/muchanipo-deep-research-max/latest_response.json")
DEFAULT_B1_FIXTURE_PATH = Path(__file__).resolve().parents[2] / "benchmarks" / "deep_research_max_plus_b1.json"
DEFAULT_CROSS_DOMAIN_MATRIX_PATH = (
    Path(__file__).resolve().parents[2] / "benchmarks" / "deep_research_cross_domain_matrix_rq46.json"
)
BENCHMARK_ID = "muchanipo-deep-research-max-plus-b1"
CROSS_DOMAIN_BENCHMARK_ID = "muchanipo-deep-research-cross-domain-matrix-rq46"
LOG_SCHEMA = "muchanipo.autoresearch_log.v1"
AHP_TARGET_SCORE = 0.86
AHP_CRITICAL_MIN_SCORE = 0.75
AHP_CRITERION_WEIGHTS: dict[str, float] = {
    "source_authority_anchor_doi_recall": 0.22,
    "claim_evidence_traceability": 0.20,
    "scientific_workflow_fidelity": 0.18,
    "non_overfit_generic_behavior": 0.14,
    "contradiction_refutation_disclosure": 0.10,
    "runtime_observability_event_quality": 0.08,
    "final_report_usefulness": 0.08,
}
AHP_CRITICAL_CRITERIA = (
    "source_authority_anchor_doi_recall",
    "claim_evidence_traceability",
    "scientific_workflow_fidelity",
    "non_overfit_generic_behavior",
    "contradiction_refutation_disclosure",
)


@dataclass(frozen=True)
class ExpectedClaim:
    id: str
    text: str
    required_terms: tuple[str, ...]
    min_matched_terms: int = 2

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("ExpectedClaim.id must not be empty")
        if not self.text.strip():
            raise ValueError("ExpectedClaim.text must not be empty")
        if not self.required_terms:
            raise ValueError("ExpectedClaim.required_terms must not be empty")
        if self.min_matched_terms < 1:
            raise ValueError("ExpectedClaim.min_matched_terms must be >= 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "required_terms": list(self.required_terms),
            "min_matched_terms": self.min_matched_terms,
        }


@dataclass(frozen=True)
class FixtureEvidenceSource:
    id: str
    query: str
    title: str
    url: str
    quote: str
    source_grade: str = "A"
    source_kind: str = "academic"

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("FixtureEvidenceSource.id must not be empty")
        if not self.query.strip():
            raise ValueError("FixtureEvidenceSource.query must not be empty")
        if not self.title.strip():
            raise ValueError("FixtureEvidenceSource.title must not be empty")
        if not self.quote.strip():
            raise ValueError("FixtureEvidenceSource.quote must not be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "query": self.query,
            "title": self.title,
            "url": self.url,
            "quote": self.quote,
            "source_grade": self.source_grade,
            "source_kind": self.source_kind,
        }


@dataclass(frozen=True)
class MaxPlusBenchmarkFixture:
    benchmark_id: str
    probe: str
    report_path: Path
    prompt_path: Path
    latest_response_path: Path
    expected_claims: tuple[ExpectedClaim, ...]
    workflow_fidelity_facets: tuple[ExpectedClaim, ...] = ()
    final_report_usefulness_facets: tuple[ExpectedClaim, ...] = ()
    source_discovery_queries: tuple[str, ...] = ()
    source_backed_evidence: tuple[FixtureEvidenceSource, ...] = ()
    must_not_call_paid_max_again: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark_id": self.benchmark_id,
            "probe": self.probe,
            "reference_report": {
                "path": str(self.report_path),
                "exists": self.report_path.exists(),
                "prompt_path": str(self.prompt_path),
                "latest_response_path": str(self.latest_response_path),
                "must_not_call_paid_max_again": self.must_not_call_paid_max_again,
            },
            "expected_claims": [claim.to_dict() for claim in self.expected_claims],
            "workflow_fidelity_facets": [claim.to_dict() for claim in self.workflow_fidelity_facets],
            "final_report_usefulness_facets": [
                claim.to_dict() for claim in self.final_report_usefulness_facets
            ],
            "source_discovery_queries": list(self.source_discovery_queries),
            "source_backed_evidence": [source.to_dict() for source in self.source_backed_evidence],
        }


@dataclass(frozen=True)
class ClaimCoverage:
    expected_count: int
    covered_count: int
    recall: float
    covered_claim_ids: tuple[str, ...]
    missing_claim_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected_count": self.expected_count,
            "covered_count": self.covered_count,
            "recall": self.recall,
            "covered_claim_ids": list(self.covered_claim_ids),
            "missing_claim_ids": list(self.missing_claim_ids),
        }


@dataclass(frozen=True)
class CrossDomainBenchmarkCase:
    domain_id: str
    title: str
    prompt: str
    expected_facets: tuple[str, ...]
    expected_source_kinds: tuple[str, ...]
    expected_claims: tuple[ExpectedClaim, ...]

    def __post_init__(self) -> None:
        if not self.domain_id.strip():
            raise ValueError("CrossDomainBenchmarkCase.domain_id must not be empty")
        if not self.title.strip():
            raise ValueError("CrossDomainBenchmarkCase.title must not be empty")
        if not self.prompt.strip():
            raise ValueError("CrossDomainBenchmarkCase.prompt must not be empty")
        if not self.expected_facets:
            raise ValueError("CrossDomainBenchmarkCase.expected_facets must not be empty")
        if not self.expected_source_kinds:
            raise ValueError("CrossDomainBenchmarkCase.expected_source_kinds must not be empty")
        if not self.expected_claims:
            raise ValueError("CrossDomainBenchmarkCase.expected_claims must not be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain_id": self.domain_id,
            "title": self.title,
            "prompt": self.prompt,
            "expected_facets": list(self.expected_facets),
            "expected_source_kinds": list(self.expected_source_kinds),
            "expected_claims": [claim.to_dict() for claim in self.expected_claims],
        }


@dataclass(frozen=True)
class CrossDomainBenchmarkMatrix:
    benchmark_id: str
    purpose: str
    cases: tuple[CrossDomainBenchmarkCase, ...]

    def __post_init__(self) -> None:
        if not self.benchmark_id.strip():
            raise ValueError("CrossDomainBenchmarkMatrix.benchmark_id must not be empty")
        if not self.cases:
            raise ValueError("CrossDomainBenchmarkMatrix.cases must not be empty")
        domain_ids = [case.domain_id for case in self.cases]
        if len(set(domain_ids)) != len(domain_ids):
            raise ValueError("CrossDomainBenchmarkMatrix case domain_id values must be unique")

    def case_by_id(self, domain_id: str) -> CrossDomainBenchmarkCase:
        for case in self.cases:
            if case.domain_id == domain_id:
                return case
        raise KeyError(domain_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark_id": self.benchmark_id,
            "purpose": self.purpose,
            "cases": [case.to_dict() for case in self.cases],
        }


@dataclass(frozen=True)
class AutoresearchLogEntry:
    hypothesis: str
    code_test_change: str
    changed_files: tuple[str, ...]
    metrics_before: Mapping[str, float]
    metrics_after: Mapping[str, float]
    decision: str
    next_slice: str
    evidence: tuple[str, ...]
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.hypothesis.strip():
            raise ValueError("hypothesis must not be empty")
        if not self.code_test_change.strip():
            raise ValueError("code_test_change must not be empty")
        if not self.changed_files:
            raise ValueError("changed_files must not be empty")
        if self.decision not in {"keep", "discard"}:
            raise ValueError("decision must be 'keep' or 'discard'")
        if not self.next_slice.strip():
            raise ValueError("next_slice must not be empty")
        if not self.evidence:
            raise ValueError("evidence must not be empty")

    def to_dict(self) -> dict[str, Any]:
        created_at = self.created_at or datetime.now(timezone.utc).isoformat()
        return {
            "schema": LOG_SCHEMA,
            "created_at": created_at,
            "hypothesis": self.hypothesis,
            "code_test_change": self.code_test_change,
            "changed_files": list(self.changed_files),
            "metrics_before": dict(self.metrics_before),
            "metrics_after": dict(self.metrics_after),
            "decision": self.decision,
            "next_slice": self.next_slice,
            "evidence": list(self.evidence),
        }


def build_b1_probe_fixture(
    *,
    report_path: Path = DEFAULT_MAX_REPORT_PATH,
    prompt_path: Path = DEFAULT_MAX_PROMPT_PATH,
    latest_response_path: Path = DEFAULT_MAX_RESPONSE_PATH,
    fixture_path: Path = DEFAULT_B1_FIXTURE_PATH,
) -> MaxPlusBenchmarkFixture:
    """Return the first Deep Research Max-Plus benchmark slice.

    The B-1 probe expected claims live in the benchmark JSON fixture so product
    source stays general-purpose and sessions must select fixtures explicitly.
    """

    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    expected_claims = tuple(
        ExpectedClaim(
            id=str(item["id"]),
            text=str(item["text"]),
            required_terms=tuple(str(term) for term in item["required_terms"]),
            min_matched_terms=int(item.get("min_matched_terms", 2)),
        )
        for item in payload["rubric"]["expected_claims"]
    )
    ahp_payload = payload.get("rubric", {}).get("ahp", {})
    workflow_fidelity_facets = _expected_claims_from_payload(
        ahp_payload.get("workflow_fidelity_facets", [])
    )
    final_report_usefulness_facets = _expected_claims_from_payload(
        ahp_payload.get("final_report_usefulness_facets", [])
    )
    source_discovery_queries = tuple(
        str(query).strip()
        for query in payload.get("source_discovery", {}).get("queries", [])
        if str(query).strip()
    )
    source_backed_evidence = tuple(
        FixtureEvidenceSource(
            id=str(item["id"]),
            query=str(item["query"]),
            title=str(item["title"]),
            url=str(item.get("url") or ""),
            quote=str(item["quote"]),
            source_grade=str(item.get("source_grade") or "A"),
            source_kind=str(item.get("source_kind") or "academic"),
        )
        for item in payload.get("source_backed_evidence", [])
    )
    return MaxPlusBenchmarkFixture(
        benchmark_id=str(payload.get("benchmark_id") or BENCHMARK_ID),
        probe=str(payload.get("probe") or "B-1"),
        report_path=report_path,
        prompt_path=prompt_path,
        latest_response_path=latest_response_path,
        expected_claims=expected_claims,
        workflow_fidelity_facets=workflow_fidelity_facets,
        final_report_usefulness_facets=final_report_usefulness_facets,
        source_discovery_queries=source_discovery_queries,
        source_backed_evidence=source_backed_evidence,
    )


def _expected_claims_from_payload(items: Sequence[Mapping[str, Any]]) -> tuple[ExpectedClaim, ...]:
    return tuple(
        ExpectedClaim(
            id=str(item["id"]),
            text=str(item["text"]),
            required_terms=tuple(str(term) for term in item["required_terms"]),
            min_matched_terms=int(item.get("min_matched_terms", 2)),
        )
        for item in items
    )


def build_cross_domain_benchmark_matrix(
    fixture_path: Path = DEFAULT_CROSS_DOMAIN_MATRIX_PATH,
) -> CrossDomainBenchmarkMatrix:
    """Load the deterministic Stage-2 cross-domain benchmark matrix.

    This fixture is deliberately domain-general: it covers evidence patterns for
    common research verticals while keeping topic-specific anchor papers/DOIs in
    opt-in benchmark fixtures only.
    """

    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    cases = []
    for item in payload.get("cases", []):
        cases.append(
            CrossDomainBenchmarkCase(
                domain_id=str(item["domain_id"]),
                title=str(item["title"]),
                prompt=str(item["prompt"]),
                expected_facets=tuple(str(facet) for facet in item["expected_facets"]),
                expected_source_kinds=tuple(str(kind) for kind in item["expected_source_kinds"]),
                expected_claims=_expected_claims_from_payload(item["expected_claims"]),
            )
        )
    return CrossDomainBenchmarkMatrix(
        benchmark_id=str(payload.get("benchmark_id") or CROSS_DOMAIN_BENCHMARK_ID),
        purpose=str(payload.get("purpose") or ""),
        cases=tuple(cases),
    )


def selected_max_plus_benchmark_fixture() -> MaxPlusBenchmarkFixture | None:
    """Return the explicitly selected Max-Plus fixture, or None for generic runs.

    Product runtime must stay general-purpose: benchmark scoring is opt-in via
    fixture ID instead of inferred from topic text or applied unconditionally.
    """

    selected = str(os.getenv("MUCHANIPO_MAX_PLUS_BENCHMARK_ID") or "").strip().casefold()
    if not selected:
        return None
    if selected in {"b1", "b-1", BENCHMARK_ID.casefold()}:
        return build_b1_probe_fixture()
    raise ValueError(f"unknown MUCHANIPO_MAX_PLUS_BENCHMARK_ID: {selected}")


def source_authority_score(ref: EvidenceRef) -> float:
    """Score source authority from grade, source kind, and resolvable anchor."""

    grade_score = {"A": 0.9, "B": 0.72, "C": 0.42, "D": 0.08}.get(str(ref.source_grade).upper(), 0.0)
    kind = _source_kind(ref)
    if kind in {"generated", "mock", "empty"}:
        return 0.0
    kind_bonus = 0.0
    if kind in {"doi", "paper", "academic", "crossref", "pubmed", "semantic_scholar"}:
        kind_bonus = 0.1
    elif kind in {"government", "statistics"}:
        kind_bonus = 0.08
    elif kind in {"industry_report", "pricing_page"}:
        kind_bonus = 0.04
    anchor_bonus = 0.0
    url = str(ref.source_url or "").casefold()
    if "doi.org/" in url or url.startswith("https://doi.org/"):
        anchor_bonus = 0.04
    elif url.startswith("https://"):
        anchor_bonus = 0.02
    return round(min(1.0, grade_score + kind_bonus + anchor_bonus), 3)


def weak_source_penalty(refs: Sequence[EvidenceRef]) -> float:
    """Return a 0..1 penalty for weak, generated, or quote-free sources."""

    if not refs:
        return 1.0
    penalties = []
    for ref in refs:
        grade = str(ref.source_grade).upper()
        kind = _source_kind(ref)
        penalty = 0.0
        if grade == "C":
            penalty += 0.35
        elif grade == "D":
            penalty += 0.75
        if kind in {"generated", "mock", "empty"}:
            penalty += 1.0
        if not str(ref.quote or "").strip():
            penalty += 0.25
        penalties.append(min(1.0, penalty))
    return round(sum(penalties) / len(penalties), 3)


def evidence_quote_coverage(findings: Sequence[Finding]) -> float:
    """Share of findings with at least one support ref carrying a quote."""

    if not findings:
        return 0.0
    covered = sum(
        1
        for finding in findings
        if any(str(ref.quote or "").strip() for ref in finding.support)
    )
    return round(covered / len(findings), 3)


def citation_density(findings: Sequence[Finding]) -> float:
    """Average number of quote-bearing support refs per finding.

    This is a deterministic Max-style density signal: it measures whether the
    report is actually carrying source-backed citations at claim granularity,
    without importing the separate eval-agent scoring stack into runtime gates.
    """

    if not findings:
        return 0.0
    cited_refs = sum(
        1
        for finding in findings
        for ref in finding.support
        if str(ref.quote or "").strip()
    )
    return round(cited_refs / len(findings), 3)


_QUANT_CLAIM_RE = re.compile(
    r"(?:\b\d+(?:\.\d+)?\s*(?:%|percent|배|x|×|cfu/ml|copies/ml|ppm|ppb|nm|μm|um|mm|cm|kg|g|mg|원|달러|usd|krw|분|초|일|년|minute|minutes|second|seconds|day|days|year|years)\b|\b\d+(?:\.\d+)?\s*(?:-|–|to)\s*\d+(?:\.\d+)?\b)",
    re.IGNORECASE,
)


def quantitative_claim_count(findings: Sequence[Finding]) -> float:
    """Count findings whose claim includes an explicit quantitative assertion."""

    return float(sum(1 for finding in findings if _QUANT_CLAIM_RE.search(finding.claim or "")))


def claim_traceability_score(findings: Sequence[Finding]) -> float:
    """Average claim-to-quote lexical overlap with light authority weighting.

    Traceability asks whether a claim points to evidence that says the same
    thing. Source weakness is scored separately, so low-authority refs reduce
    but do not erase lexical traceability.
    """

    if not findings:
        return 0.0
    scores: list[float] = []
    for finding in findings:
        claim_terms = _terms(finding.claim)
        if not claim_terms or not finding.support:
            scores.append(0.0)
            continue
        best = 0.0
        for ref in finding.support:
            quote_terms = _terms(" ".join(str(value or "") for value in (ref.source_title, ref.quote)))
            overlap = len(claim_terms & quote_terms) / max(1, min(len(claim_terms), 8))
            authority_weight = 0.5 + (0.5 * source_authority_score(ref))
            best = max(best, min(1.0, overlap) * authority_weight)
        scores.append(best)
    return round(sum(scores) / len(scores), 3)


def expected_claim_coverage(
    findings: Sequence[Finding],
    expected_claims: Sequence[ExpectedClaim],
    *,
    accepted_source_ids: Iterable[str] | None = None,
) -> ClaimCoverage:
    """Measure fixture-scoped expected-claim recall.

    Evidence-backed runs delegate coverage to the generic evidence ledger, so a
    benchmark claim is covered only by an accepted support edge. For explicit
    fixture-local session-isolation probes that intentionally pass claim text
    without retrieval support, keep a text-only recall fallback; this fallback is
    disabled whenever a source-audit allowlist is supplied and it never improves
    material support, quote coverage, traceability, or readiness metrics.
    """

    if not expected_claims:
        return ClaimCoverage(0, 0, 0.0, (), ())
    allowlist_supplied = accepted_source_ids is not None
    ledger = build_evidence_ledger_report(
        findings,
        expected_claims=expected_claims,
        accepted_source_ids=accepted_source_ids,
    )
    covered: list[str] = []
    missing: list[str] = []
    for expected in expected_claims:
        row = ledger.expected_claim_traceability.get(expected.id, {})
        supported = bool(row.get("supported"))
        if not supported and not allowlist_supplied:
            supported = _unsupported_fixture_claim_text_matches(findings, expected)
        if supported:
            covered.append(expected.id)
        else:
            missing.append(expected.id)
    recall = round(len(covered) / len(expected_claims), 3)
    return ClaimCoverage(
        expected_count=len(expected_claims),
        covered_count=len(covered),
        recall=recall,
        covered_claim_ids=tuple(covered),
        missing_claim_ids=tuple(missing),
    )


def _unsupported_fixture_claim_text_matches(findings: Sequence[Finding], expected: ExpectedClaim) -> bool:
    required_terms = {_normalize_term(term) for term in expected.required_terms if _normalize_term(term)}
    if not required_terms:
        return False
    min_matched = max(1, int(expected.min_matched_terms or 1))
    for finding in findings:
        if finding.support:
            continue
        claim_terms = _terms(finding.claim)
        if len(required_terms & claim_terms) >= min_matched:
            return True
    return False


anchor_claim_recall = expected_claim_coverage


def build_quality_gate_event(
    *,
    benchmark_id: str,
    metrics: Mapping[str, float],
    decision: str,
    hypothesis: str,
    ahp_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a stable progress event for future Tauri display."""

    if decision not in {"keep", "discard", "blocked"}:
        raise ValueError("decision must be keep, discard, or blocked")
    event = {
        "event": "research_progress",
        "stage": "quality_gate",
        "status": "max_plus_benchmark_scored",
        "research_backend_contract_version": RESEARCH_BACKEND_CONTRACT_VERSION,
        "benchmark_id": benchmark_id,
        "decision": decision,
        "hypothesis": hypothesis,
        "metrics": dict(metrics),
    }
    if ahp_report is not None:
        event["ahp_quality_gate"] = dict(ahp_report)
        event["ahp_score"] = ahp_report.get("score")
        event["ahp_passed"] = ahp_report.get("passed")
    return event


def append_autoresearch_log_entry(path: Path, entry: AutoresearchLogEntry) -> None:
    """Append one JSONL experiment decision without rewriting previous rows."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")


def cross_domain_benchmark_metrics(
    matrix: CrossDomainBenchmarkMatrix,
    findings_by_case: Mapping[str, Sequence[Finding]],
    *,
    accepted_source_ids_by_case: Mapping[str, Iterable[str]] | None = None,
) -> dict[str, float]:
    """Score a set of offline domain cases against the generic benchmark matrix.

    The hook intentionally reuses source-authority, quote, traceability, and
    expected-claim scoring primitives while adding matrix-level domain/facet
    coverage and a guardrail that flags leakage from named scientific fixtures.
    """

    case_count = len(matrix.cases)
    if case_count == 0:
        return {
            "case_count": 0,
            "covered_case_count": 0,
            "domain_coverage": 0.0,
            "facet_coverage": 0.0,
            "source_kind_coverage": 0.0,
            "average_expected_claim_recall": 0.0,
            "average_source_authority_score": 0.0,
            "average_claim_traceability": 0.0,
            "b1_overfit_leak_count": 0,
        }

    accepted_source_ids_by_case = accepted_source_ids_by_case or {}
    covered_case_count = 0
    recall_scores: list[float] = []
    authority_scores: list[float] = []
    traceability_scores: list[float] = []
    expected_facets_for_covered: set[tuple[str, str]] = set()
    observed_facets: set[tuple[str, str]] = set()
    expected_kinds_for_covered: set[tuple[str, str]] = set()
    observed_kinds: set[tuple[str, str]] = set()
    leak_text_parts: list[str] = [matrix.purpose]

    for case in matrix.cases:
        findings = list(findings_by_case.get(case.domain_id, ()))
        allowlist = (
            set(accepted_source_ids_by_case[case.domain_id])
            if case.domain_id in accepted_source_ids_by_case
            else None
        )
        scored_findings = _findings_with_allowed_support(findings, allowlist)
        refs = _dedupe_refs(ref for finding in scored_findings for ref in finding.support)
        if findings:
            covered_case_count += 1
            expected_facets_for_covered.update((case.domain_id, facet) for facet in case.expected_facets)
            expected_kinds_for_covered.update((case.domain_id, kind) for kind in case.expected_source_kinds)
        for finding in scored_findings:
            leak_text_parts.append(finding.claim)
            for ref in finding.support:
                leak_text_parts.extend(str(value or "") for value in (ref.source_title, ref.source_url, ref.quote))
                facet = _ref_facet_id(ref)
                if facet:
                    observed_facets.add((case.domain_id, facet))
                observed_kinds.add((case.domain_id, _source_kind(ref)))
        coverage = expected_claim_coverage(
            findings,
            case.expected_claims,
            accepted_source_ids=allowlist,
        )
        recall_scores.append(coverage.recall)
        authority = sum(source_authority_score(ref) for ref in refs) / len(refs) if refs else 0.0
        authority_scores.append(authority)
        traceability_scores.append(claim_traceability_score(scored_findings))

    facet_hits = observed_facets & expected_facets_for_covered
    kind_hits = observed_kinds & expected_kinds_for_covered
    return {
        "case_count": case_count,
        "covered_case_count": covered_case_count,
        "domain_coverage": round(covered_case_count / case_count, 3),
        "facet_coverage": round(len(facet_hits) / len(expected_facets_for_covered), 3)
        if expected_facets_for_covered
        else 0.0,
        "source_kind_coverage": round(len(kind_hits) / len(expected_kinds_for_covered), 3)
        if expected_kinds_for_covered
        else 0.0,
        "average_expected_claim_recall": round(sum(recall_scores) / case_count, 3),
        "average_source_authority_score": round(sum(authority_scores) / case_count, 3),
        "average_claim_traceability": round(sum(traceability_scores) / case_count, 3),
        "b1_overfit_leak_count": _b1_overfit_leak_count("\n".join(leak_text_parts)),
    }


def benchmark_metrics(
    findings: Sequence[Finding],
    fixture: MaxPlusBenchmarkFixture | None = None,
    *,
    accepted_source_ids: Iterable[str] | None = None,
) -> dict[str, float]:
    """Compute the first Max-Plus score vector for report comparisons.

    When the runtime source audit supplies an allowlist, benchmark scoring uses
    only item-level accepted sources. Authority-shaped but off-topic references
    may still be present in findings for diagnostics, but they cannot improve
    recall, quote coverage, traceability, or ledger metrics.
    """

    if fixture is None:
        raise ValueError("benchmark_metrics requires an explicit benchmark fixture selection")
    allowlist = set(accepted_source_ids) if accepted_source_ids is not None else None
    scored_findings = _findings_with_allowed_support(findings, allowlist)
    refs = _dedupe_refs(ref for finding in scored_findings for ref in finding.support)
    coverage = expected_claim_coverage(
        findings,
        fixture.expected_claims,
        accepted_source_ids=allowlist,
    )
    ledger = build_evidence_ledger_report(
        findings,
        expected_claims=fixture.expected_claims,
        accepted_source_ids=allowlist,
    )
    authority = sum(source_authority_score(ref) for ref in refs) / len(refs) if refs else 0.0
    anchor_coverage = anchor_doi_coverage(
        findings,
        fixture=fixture,
        accepted_source_ids=allowlist,
    )
    return {
        "source_authority_score": round(authority, 3),
        "weak_source_penalty": weak_source_penalty(refs),
        "expected_claim_recall": coverage.recall,
        "anchor_doi_recall": anchor_coverage["recall"],
        "required_anchor_doi_count": float(anchor_coverage["required_count"]),
        "covered_anchor_doi_count": float(anchor_coverage["covered_count"]),
        "evidence_quote_coverage": evidence_quote_coverage(scored_findings),
        "citation_density": citation_density(scored_findings),
        "quant_claim_count": quantitative_claim_count(scored_findings),
        "claim_traceability": claim_traceability_score(scored_findings),
        "material_claim_support_coverage": ledger.metrics["material_claim_support_coverage"],
        "expected_claim_traceability_score": ledger.metrics["expected_claim_traceability_score"],
        "quote_locator_coverage": ledger.metrics["quote_locator_coverage"],
        "citation_integrity_score": ledger.metrics["citation_integrity_score"],
        "background_leak_count": ledger.metrics["background_leak_count"],
        "unsupported_high_confidence_claim_count": ledger.metrics[
            "unsupported_high_confidence_claim_count"
        ],
        "unresolved_conflict_disclosure_rate": ledger.metrics[
            "unresolved_conflict_disclosure_rate"
        ],
    }


def anchor_doi_coverage(
    findings: Sequence[Finding],
    *,
    fixture: MaxPlusBenchmarkFixture,
    accepted_source_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Measure recall for DOI anchors declared by an explicit benchmark fixture."""

    required = _required_anchor_dois(fixture)
    allowlist = set(accepted_source_ids) if accepted_source_ids is not None else None
    scored_findings = _findings_with_allowed_support(findings, allowlist)
    observed = set(_extract_dois(_findings_text(scored_findings)))
    covered = tuple(doi for doi in required if doi in observed)
    missing = tuple(doi for doi in required if doi not in observed)
    return {
        "required": list(required),
        "covered": list(covered),
        "missing": list(missing),
        "required_count": len(required),
        "covered_count": len(covered),
        "recall": round(len(covered) / len(required), 3) if required else 1.0,
    }


def ahp_quality_gate_report(
    findings: Sequence[Finding],
    *,
    fixture: MaxPlusBenchmarkFixture,
    accepted_source_ids: Iterable[str] | None = None,
    benchmark_score_vector: Mapping[str, float] | None = None,
    progress_events: Sequence[Mapping[str, Any]] = (),
    final_report_text: str = "",
    reference_report_text: str = "",
    cross_domain_metrics: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Build a fixture-scoped AHP quality report without changing runtime behavior.

    The scoring surface is generic: domain-specific facets and anchors come from
    the explicit benchmark fixture, not topic sniffing or product code branches.
    """

    allowlist = set(accepted_source_ids) if accepted_source_ids is not None else None
    metrics = dict(
        benchmark_score_vector
        or benchmark_metrics(findings, fixture=fixture, accepted_source_ids=allowlist)
    )
    anchor_coverage = anchor_doi_coverage(
        findings,
        fixture=fixture,
        accepted_source_ids=allowlist,
    )
    evidence_text = _findings_text(_findings_with_allowed_support(findings, allowlist))
    candidate_report_text = str(final_report_text or "")
    comparison_text = "\n".join(
        part for part in (evidence_text, candidate_report_text, str(reference_report_text or "")) if part
    )
    criterion_scores = {
        "source_authority_anchor_doi_recall": _bounded_score(
            (0.55 * _metric(metrics, "source_authority_score"))
            + (0.45 * anchor_coverage["recall"])
        ),
        "claim_evidence_traceability": _average_score(
            _metric(metrics, "claim_traceability"),
            _metric(metrics, "quote_locator_coverage"),
            _metric(metrics, "citation_integrity_score"),
            _metric(metrics, "material_claim_support_coverage"),
            _metric(metrics, "expected_claim_traceability_score"),
            _metric(metrics, "evidence_quote_coverage"),
        ),
        "scientific_workflow_fidelity": _facet_term_coverage(
            comparison_text,
            fixture.workflow_fidelity_facets or fixture.expected_claims,
        ),
        "non_overfit_generic_behavior": _non_overfit_generic_score(
            metrics,
            cross_domain_metrics=cross_domain_metrics or {},
        ),
        "contradiction_refutation_disclosure": _average_score(
            _metric(metrics, "unresolved_conflict_disclosure_rate", empty=1.0),
            _metric(metrics, "material_contradiction_disclosure_rate", empty=1.0),
        ),
        "runtime_observability_event_quality": _runtime_observability_score(progress_events),
        "final_report_usefulness": _facet_term_coverage(
            candidate_report_text,
            fixture.final_report_usefulness_facets or fixture.expected_claims,
        )
        if candidate_report_text.strip()
        else 0.0,
    }
    weighted_score = round(
        sum(criterion_scores[key] * AHP_CRITERION_WEIGHTS[key] for key in AHP_CRITERION_WEIGHTS),
        3,
    )
    critical_below_min = {
        key: criterion_scores[key]
        for key in AHP_CRITICAL_CRITERIA
        if criterion_scores[key] < AHP_CRITICAL_MIN_SCORE
    }
    passed = (
        weighted_score >= AHP_TARGET_SCORE
        and not critical_below_min
        and not anchor_coverage["missing"]
    )
    return {
        "schema": "muchanipo.max_plus_ahp.v1",
        "benchmark_id": fixture.benchmark_id,
        "score": weighted_score,
        "passed": passed,
        "target_score": AHP_TARGET_SCORE,
        "critical_min_score": AHP_CRITICAL_MIN_SCORE,
        "criteria_weights": dict(AHP_CRITERION_WEIGHTS),
        "criterion_scores": criterion_scores,
        "critical_criteria_below_min": critical_below_min,
        "anchor_doi_recall": anchor_coverage["recall"],
        "required_anchor_dois": anchor_coverage["required"],
        "covered_anchor_dois": anchor_coverage["covered"],
        "missing_anchor_dois": anchor_coverage["missing"],
        "report_state": "available" if candidate_report_text.strip() else "not_available",
        "top_gaps": _ahp_top_gaps(criterion_scores, anchor_coverage),
        "benchmark_metrics": metrics,
    }


def _dedupe_refs(refs: Iterable[EvidenceRef]) -> list[EvidenceRef]:
    out: list[EvidenceRef] = []
    seen: set[str] = set()
    for ref in refs:
        if ref.id in seen:
            continue
        seen.add(ref.id)
        out.append(ref)
    return out


def _findings_with_allowed_support(
    findings: Sequence[Finding],
    accepted_source_ids: set[str] | None,
) -> list[Finding]:
    if accepted_source_ids is None:
        return list(findings)
    return [
        Finding(
            claim=finding.claim,
            support=[ref for ref in finding.support if ref.id in accepted_source_ids],
            confidence=finding.confidence,
            limitations=list(finding.limitations),
        )
        for finding in findings
    ]


def _required_anchor_dois(fixture: MaxPlusBenchmarkFixture) -> tuple[str, ...]:
    parts: list[str] = []
    parts.extend(claim.text for claim in fixture.expected_claims)
    parts.extend(fixture.source_discovery_queries)
    for source in fixture.source_backed_evidence:
        parts.extend((source.id, source.query, source.title, source.url, source.quote))
    seen: set[str] = set()
    out: list[str] = []
    for doi in _extract_dois("\n".join(parts)):
        if doi in seen:
            continue
        seen.add(doi)
        out.append(doi)
    return tuple(out)


def _extract_dois(text: str) -> tuple[str, ...]:
    import re

    values: list[str] = []
    for match in re.findall(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", str(text or "")):
        doi = match.strip().strip(".,;:)])}>").casefold()
        if doi:
            values.append(doi)
    return tuple(values)


def _findings_text(findings: Sequence[Finding]) -> str:
    parts: list[str] = []
    for finding in findings:
        parts.append(str(finding.claim or ""))
        parts.extend(str(item or "") for item in finding.limitations)
        for ref in finding.support:
            parts.extend(
                str(value or "")
                for value in (
                    ref.id,
                    ref.source_url,
                    ref.source_title,
                    ref.quote,
                    json.dumps(ref.provenance or {}, ensure_ascii=False, sort_keys=True),
                )
            )
    return "\n".join(parts)


def _metric(metrics: Mapping[str, Any], key: str, *, empty: float = 0.0) -> float:
    value = metrics.get(key, empty)
    if value is None:
        value = empty
    try:
        return _bounded_score(float(value))
    except (TypeError, ValueError):
        return _bounded_score(empty)


def _bounded_score(value: float) -> float:
    return round(max(0.0, min(1.0, float(value))), 3)


def _average_score(*values: float) -> float:
    usable = [max(0.0, min(1.0, float(value))) for value in values]
    return round(sum(usable) / len(usable), 3) if usable else 0.0


def _facet_term_coverage(text: str, facets: Sequence[ExpectedClaim]) -> float:
    if not facets:
        return 1.0
    corpus_terms = _terms(text)
    covered = 0
    for facet in facets:
        required = {_normalize_term(term) for term in facet.required_terms if _normalize_term(term)}
        if not required:
            continue
        if len(required & corpus_terms) >= int(facet.min_matched_terms or 1):
            covered += 1
    return round(covered / len(facets), 3)


def _non_overfit_generic_score(
    metrics: Mapping[str, Any],
    *,
    cross_domain_metrics: Mapping[str, Any],
) -> float:
    weak_penalty = _metric(metrics, "weak_source_penalty")
    background_penalty = min(1.0, float(metrics.get("background_leak_count", 0.0) or 0.0))
    unsupported_penalty = min(
        1.0,
        float(metrics.get("unsupported_high_confidence_claim_count", 0.0) or 0.0),
    )
    b1_leak_penalty = min(
        1.0,
        float(cross_domain_metrics.get("b1_overfit_leak_count", 0.0) or 0.0),
    )
    penalty = (
        0.35 * weak_penalty
        + 0.25 * background_penalty
        + 0.25 * unsupported_penalty
        + 0.15 * b1_leak_penalty
    )
    return _bounded_score(1.0 - penalty)


def _runtime_observability_score(progress_events: Sequence[Mapping[str, Any]]) -> float:
    if not progress_events:
        return 0.0
    statuses = {str(event.get("status") or "") for event in progress_events}
    required_statuses = {
        "source_audit_gate",
        "source_decision_ledger_built",
        "claim_evidence_gate",
        "evidence_ledger_built",
        "max_plus_benchmark_scored",
    }
    status_coverage = len(required_statuses & statuses) / len(required_statuses)
    quality_stage_seen = any(str(event.get("stage") or "") == "quality_gate" for event in progress_events)
    contract_seen = any(
        str(event.get("research_backend_contract_version") or "").strip()
        for event in progress_events
    )
    structure_score = 0.5 if quality_stage_seen else 0.0
    contract_score = 1.0 if contract_seen else structure_score
    return _bounded_score((0.75 * status_coverage) + (0.25 * contract_score))


def _ahp_top_gaps(
    criterion_scores: Mapping[str, float],
    anchor_coverage: Mapping[str, Any],
) -> list[str]:
    gaps: list[tuple[float, str]] = []
    for missing in anchor_coverage.get("missing", []):
        gaps.append((0.0, f"missing_anchor_doi:{missing}"))
    for criterion, score in criterion_scores.items():
        if score < AHP_TARGET_SCORE:
            gaps.append((score, f"{criterion}:{score:.3f}"))
    return [gap for _, gap in sorted(gaps, key=lambda item: item[0])[:5]]


def _ref_facet_id(ref: EvidenceRef) -> str:
    provenance = ref.provenance or {}
    metadata = provenance.get("metadata") if isinstance(provenance.get("metadata"), dict) else {}
    return str(metadata.get("facet_id") or provenance.get("facet_id") or "").strip()


def _b1_overfit_leak_count(text: str) -> int:
    haystack = str(text or "").casefold()
    leak_markers = (
        "erwinia",
        "amylovora",
        "fire blight",
        "10.1016/j.isci",
        "10.1016/j.xpro",
        "106557",
        "102412",
    )
    return sum(1 for marker in leak_markers if marker in haystack)


def _source_kind(ref: EvidenceRef) -> str:
    provenance = ref.provenance or {}
    metadata = provenance.get("metadata") if isinstance(provenance.get("metadata"), dict) else {}
    raw_kind = str(provenance.get("kind") or metadata.get("kind") or "").strip().casefold()
    url = str(ref.source_url or "").casefold()
    title = str(ref.source_title or "").casefold()
    text = f"{raw_kind} {url} {title}".casefold()
    if raw_kind in {"mock", "empty", "generated"}:
        return raw_kind
    if "doi.org/" in url or raw_kind == "doi":
        return "doi"
    if raw_kind in {"academic", "openalex", "crossref", "pubmed", "semantic_scholar"}:
        return raw_kind
    if any(marker in text for marker in ("government", ".gov", "ministry", "kosis")):
        return "government"
    if any(marker in text for marker in ("statistics", "statista", "market size")):
        return "statistics"
    if any(marker in text for marker in ("industry report", "market report")):
        return "industry_report"
    if any(marker in text for marker in ("price", "pricing", "catalog")):
        return "pricing_page"
    return raw_kind or "web"


def _terms(text: str) -> set[str]:
    import re

    raw_terms = re.findall(r"[A-Za-z0-9]+|[가-힣]{2,}", str(text or ""))
    normalized = {_normalize_term(term) for term in raw_terms}
    expanded = set(normalized)
    if "korean" in normalized:
        expanded.add("korea")
    if "farmers" in normalized or "farmer" in normalized:
        expanded.add("farmer")
        expanded.add("farm")
    if "farms" in normalized:
        expanded.add("farm")
    if "assays" in normalized:
        expanded.add("assay")
    if "diagnostics" in normalized:
        expanded.add("diagnostic")
    return {term for term in expanded if term}


def _normalize_term(term: str) -> str:
    value = str(term or "").strip().casefold()
    if value.endswith("ies") and len(value) > 4:
        return value[:-3] + "y"
    if value.endswith("s") and len(value) > 3:
        return value[:-1]
    return value
