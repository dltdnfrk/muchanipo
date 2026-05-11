"""Max-Plus benchmark contracts for source-grounded autoresearch.

This module does not call Gemini/Deep Research Max. It only records a local
reference report path and scores Muchanipo outputs against explicit,
source-grounded expectations.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from src.evidence.artifact import EvidenceRef, Finding
from src.research.evidence_ledger import build_evidence_ledger_report


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
    changed_files: tuple[str, ...]
    metrics_before: Mapping[str, float]
    metrics_after: Mapping[str, float]
    decision: str
    evidence: tuple[str, ...]
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.hypothesis.strip():
            raise ValueError("hypothesis must not be empty")
        if not self.changed_files:
            raise ValueError("changed_files must not be empty")
        if self.decision not in {"keep", "discard"}:
            raise ValueError("decision must be 'keep' or 'discard'")
        if not self.evidence:
            raise ValueError("evidence must not be empty")

    def to_dict(self) -> dict[str, Any]:
        created_at = self.created_at or datetime.now(timezone.utc).isoformat()
        return {
            "schema": LOG_SCHEMA,
            "created_at": created_at,
            "hypothesis": self.hypothesis,
            "changed_files": list(self.changed_files),
            "metrics_before": dict(self.metrics_before),
            "metrics_after": dict(self.metrics_after),
            "decision": self.decision,
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
) -> dict[str, Any]:
    """Build a stable progress event for future Tauri display."""

    if decision not in {"keep", "discard", "blocked"}:
        raise ValueError("decision must be keep, discard, or blocked")
    return {
        "event": "research_progress",
        "stage": "quality_gate",
        "status": "max_plus_benchmark_scored",
        "benchmark_id": benchmark_id,
        "decision": decision,
        "hypothesis": hypothesis,
        "metrics": dict(metrics),
    }


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
    return {
        "source_authority_score": round(authority, 3),
        "weak_source_penalty": weak_source_penalty(refs),
        "expected_claim_recall": coverage.recall,
        "evidence_quote_coverage": evidence_quote_coverage(scored_findings),
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
