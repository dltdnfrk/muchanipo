"""Generic evidence ledger and claim traceability contracts.

The ledger is intentionally domain-neutral. Benchmark-specific expected claims may
be passed in explicitly by fixture code, but this module never infers a fixture
from topic text and contains no benchmark-domain branches.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from src.evidence.artifact import EvidenceRef, Finding
from src.research.source_decision_ledger import SourceDecisionLedger


MIN_SUPPORT_QUOTE_OVERLAP = 0.125


@dataclass(frozen=True)
class SourceLedgerEntry:
    id: str
    title: str
    locator: str
    source_grade: str
    source_kind: str
    source_role: str
    authority_level: str
    accepted: bool
    rejection_reason: str
    has_locator: bool
    has_quote: bool
    canonical_id: str | None = None
    canonical_url: str | None = None
    source_decision: str = ""
    resolver_status: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "locator": self.locator,
            "source_grade": self.source_grade,
            "source_kind": self.source_kind,
            "source_role": self.source_role,
            "authority_level": self.authority_level,
            "accepted": self.accepted,
            "rejection_reason": self.rejection_reason,
            "has_locator": self.has_locator,
            "has_quote": self.has_quote,
            "canonical_id": self.canonical_id,
            "canonical_url": self.canonical_url,
            "source_decision": self.source_decision,
            "resolver_status": self.resolver_status,
        }


@dataclass(frozen=True)
class ClaimSupportEdge:
    claim_id: str
    source_id: str
    support_type: str
    supported: bool
    source_role: str
    authority_level: str
    accepted: bool
    has_locator: bool
    has_quote: bool
    quote_overlap: float
    canonical_id: str | None = None
    source_decision: str = ""
    verification_status: str = "not_found"
    claim_type: str = "unsupported"
    url_verified: bool = False
    passage_found: bool = False
    directly_supports_claim: bool = False
    weak_support: bool = False
    contradiction: bool = False
    not_found: bool = True
    verification_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "source_id": self.source_id,
            "support_type": self.support_type,
            "supported": self.supported,
            "source_role": self.source_role,
            "authority_level": self.authority_level,
            "accepted": self.accepted,
            "has_locator": self.has_locator,
            "has_quote": self.has_quote,
            "quote_overlap": self.quote_overlap,
            "canonical_id": self.canonical_id,
            "source_decision": self.source_decision,
            "verification_status": self.verification_status,
            "claim_type": self.claim_type,
            "url_verified": self.url_verified,
            "passage_found": self.passage_found,
            "directly_supports_claim": self.directly_supports_claim,
            "weak_support": self.weak_support,
            "contradiction": self.contradiction,
            "not_found": self.not_found,
            "verification_reason": self.verification_reason,
        }


@dataclass(frozen=True)
class ClaimLedgerEntry:
    id: str
    claim: str
    claim_role: str
    confidence: float
    claim_type: str
    support_edges: tuple[ClaimSupportEdge, ...] = field(default_factory=tuple)
    limitations: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_accepted_support(self) -> bool:
        return any(edge.supported for edge in self.support_edges)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "claim": self.claim,
            "claim_role": self.claim_role,
            "claim_type": self.claim_type,
            "confidence": self.confidence,
            "support_edges": [edge.to_dict() for edge in self.support_edges],
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class UncertaintyLedgerEntry:
    id: str
    text: str
    status: str
    source_ids: tuple[str, ...] = field(default_factory=tuple)
    conflict: bool = False
    disclosed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "status": self.status,
            "source_ids": list(self.source_ids),
            "conflict": self.conflict,
            "disclosed": self.disclosed,
        }


@dataclass(frozen=True)
class EvidenceLedgerReport:
    source_entries: tuple[SourceLedgerEntry, ...]
    claim_entries: tuple[ClaimLedgerEntry, ...]
    uncertainty_entries: tuple[UncertaintyLedgerEntry, ...]
    metrics: Mapping[str, float]
    readiness: str
    quality_gate_events: tuple[dict[str, Any], ...]
    expected_claim_traceability: Mapping[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_entries": [entry.to_dict() for entry in self.source_entries],
            "claim_entries": [entry.to_dict() for entry in self.claim_entries],
            "uncertainty_entries": [entry.to_dict() for entry in self.uncertainty_entries],
            "metrics": dict(self.metrics),
            "readiness": self.readiness,
            "quality_gate_events": [dict(event) for event in self.quality_gate_events],
            "expected_claim_traceability": {
                key: dict(value) for key, value in self.expected_claim_traceability.items()
            },
        }


def build_evidence_ledger_report(
    findings: Sequence[Finding],
    *,
    expected_claims: Sequence[Any] | None = None,
    accepted_source_ids: Iterable[str] | None = None,
    rejected_source_reasons: Mapping[str, str] | None = None,
    source_decision_ledger: SourceDecisionLedger | None = None,
) -> EvidenceLedgerReport:
    """Build a JSON-serializable source/claim/uncertainty ledger.

    `expected_claims` is an explicit fixture/config hook. Generic runs should pass
    nothing and therefore never load benchmark claims by accidental topic text.

    `accepted_source_ids` is the generic item-level source-audit allowlist from
    the runtime research-quality pass. When present, source metadata/provenance
    cannot self-declare acceptance; only ids accepted by the audit may support
    claim, traceability, or ledger metrics.
    """

    decision_by_id = (
        {decision.source_id: decision for decision in source_decision_ledger.decisions}
        if source_decision_ledger is not None
        else {}
    )
    source_entries = tuple(
        _source_entries(
            findings,
            accepted_source_ids=set(accepted_source_ids) if accepted_source_ids is not None else None,
            rejected_source_reasons=rejected_source_reasons or {},
            decisions_by_id=decision_by_id,
        )
    )
    source_by_id = {entry.id: entry for entry in source_entries}
    claim_entries = tuple(_claim_entries(findings, source_by_id))
    uncertainty_entries = tuple(_uncertainty_entries(claim_entries))
    expected_traceability = _expected_claim_traceability(findings, source_by_id, expected_claims or ())
    contradiction_disclosures = _contradiction_disclosures(claim_entries)
    metrics = _metrics(source_entries, claim_entries, uncertainty_entries, expected_traceability)
    readiness = _readiness(metrics)
    return EvidenceLedgerReport(
        source_entries=source_entries,
        claim_entries=claim_entries,
        uncertainty_entries=uncertainty_entries,
        metrics=metrics,
        readiness=readiness,
        quality_gate_events=_quality_gate_events(metrics, contradiction_disclosures=contradiction_disclosures),
        expected_claim_traceability=expected_traceability,
    )


def _source_entries(
    findings: Sequence[Finding],
    *,
    accepted_source_ids: set[str] | None = None,
    rejected_source_reasons: Mapping[str, str],
    decisions_by_id: Mapping[str, Any] | None = None,
) -> list[SourceLedgerEntry]:
    entries: list[SourceLedgerEntry] = []
    seen: set[str] = set()
    for ref in (ref for finding in findings for ref in finding.support):
        if ref.id in seen:
            continue
        seen.add(ref.id)
        provenance = ref.provenance or {}
        metadata = provenance.get("metadata") if isinstance(provenance.get("metadata"), dict) else {}
        source_kind = _source_kind(ref)
        source_role = _clean_token(
            provenance.get("source_role")
            or provenance.get("role")
            or metadata.get("source_role")
            or _default_source_role(source_kind)
        )
        authority_level = _clean_token(
            provenance.get("authority_level")
            or metadata.get("authority_level")
            or _default_authority_level(ref.source_grade, source_kind)
        )
        locator = str(ref.source_url or provenance.get("source") or provenance.get("url") or metadata.get("locator") or "").strip()
        quote = str(ref.quote or metadata.get("source_text") or "").strip()
        decision = (decisions_by_id or {}).get(ref.id)
        accepted = bool(decision.accepted) if decision is not None else _accepted(ref, source_kind, source_role, accepted_source_ids=accepted_source_ids)
        if decision is not None:
            source_kind = str(decision.source_kind or source_kind)
            source_role = str(decision.source_role or source_role)
            authority_level = str(decision.authority_level or authority_level)
            locator = str(decision.raw_url or locator)
            quote = quote or ("present" if decision.quote_present else "")
        rejection_reason = ""
        if not accepted:
            rejection_reason = str(
                (decision.reason if decision is not None else "")
                or rejected_source_reasons.get(ref.id)
                or provenance.get("rejection_reason")
                or metadata.get("rejection_reason")
                or _default_rejection_reason(ref, source_kind, source_role)
            )
        entries.append(
            SourceLedgerEntry(
                id=ref.id,
                title=str(ref.source_title or "").strip(),
                locator=locator,
                source_grade=str(ref.source_grade or "").upper(),
                source_kind=source_kind,
                source_role=source_role,
                authority_level=authority_level,
                accepted=accepted,
                rejection_reason=rejection_reason,
                has_locator=bool(locator),
                has_quote=bool(quote),
                canonical_id=str(decision.canonical_id) if decision is not None and decision.canonical_id else None,
                canonical_url=str(decision.canonical_url) if decision is not None and decision.canonical_url else None,
                source_decision=str(decision.decision) if decision is not None else "",
                resolver_status=str(decision.resolver_status) if decision is not None else "",
            )
        )
    return entries


def _claim_entries(findings: Sequence[Finding], source_by_id: Mapping[str, SourceLedgerEntry]) -> list[ClaimLedgerEntry]:
    entries: list[ClaimLedgerEntry] = []
    for index, finding in enumerate(findings, start=1):
        claim_id = f"claim-{index:03d}"
        role = _claim_role(finding)
        edges = tuple(_support_edge(claim_id, finding, ref, source_by_id.get(ref.id), role) for ref in finding.support)
        entries.append(
            ClaimLedgerEntry(
                id=claim_id,
                claim=finding.claim,
                claim_role=role,
                claim_type=_claim_type_for_edges(finding, edges),
                confidence=round(float(finding.confidence or 0.0), 3),
                support_edges=edges,
                limitations=tuple(str(item) for item in finding.limitations),
            )
        )
    return entries


def _support_edge(
    claim_id: str,
    finding: Finding,
    ref: EvidenceRef,
    source: SourceLedgerEntry | None,
    claim_role: str,
) -> ClaimSupportEdge:
    if source is None:
        source = SourceLedgerEntry(ref.id, "", "", "D", "unknown", "unknown", "low", False, "missing source entry", False, False)
    overlap = _claim_quote_overlap(finding.claim, ref)
    explicit_verification_status = _explicit_verification_status(ref)
    can_support = (
        explicit_verification_status not in {"weak_support", "passage_found", "url_verified", "not_found", "contradiction"}
        and source.accepted
        and source.has_quote
        and source.has_locator
        and source.source_role != "background"
        and claim_role == "material"
        and overlap >= MIN_SUPPORT_QUOTE_OVERLAP
    )
    if can_support:
        support_type = "accepted_direct"
    elif source.source_role == "background":
        support_type = "background"
    elif not source.accepted:
        support_type = "rejected"
    elif not source.has_quote or not source.has_locator:
        support_type = "incomplete_citation"
    elif (
        source.accepted
        and source.has_quote
        and source.has_locator
        and source.source_role != "background"
        and claim_role == "material"
        and overlap >= MIN_SUPPORT_QUOTE_OVERLAP
    ):
        support_type = "weak_support"
    elif explicit_verification_status == "weak_support":
        support_type = "weak_support"
    elif claim_role == "material" and overlap < MIN_SUPPORT_QUOTE_OVERLAP:
        support_type = "off_topic_quote"
    else:
        support_type = "non_material"
    verification_status = _verification_status(
        can_support=can_support,
        source=source,
        claim_role=claim_role,
        quote_overlap=overlap,
        explicit_verification_status=explicit_verification_status,
    )
    claim_type = _edge_claim_type(finding, verification_status)
    return ClaimSupportEdge(
        claim_id=claim_id,
        source_id=ref.id,
        support_type=support_type,
        supported=can_support,
        source_role=source.source_role,
        authority_level=source.authority_level,
        accepted=source.accepted,
        has_locator=source.has_locator,
        has_quote=source.has_quote,
        quote_overlap=overlap,
        canonical_id=source.canonical_id,
        source_decision=source.source_decision,
        verification_status=verification_status,
        claim_type=claim_type,
        url_verified=source.has_locator,
        passage_found=source.has_quote,
        directly_supports_claim=verification_status == "directly_supports_claim",
        weak_support=verification_status == "weak_support",
        contradiction=verification_status == "contradiction",
        not_found=verification_status == "not_found",
        verification_reason=_verification_reason(verification_status, support_type),
    )


def _verification_status(
    *,
    can_support: bool,
    source: SourceLedgerEntry,
    claim_role: str,
    quote_overlap: float,
    explicit_verification_status: str = "",
) -> str:
    if explicit_verification_status in {
        "directly_supports_claim",
        "weak_support",
        "passage_found",
        "url_verified",
        "contradiction",
        "not_found",
    }:
        return explicit_verification_status
    if can_support:
        return "directly_supports_claim"
    if not source.has_locator:
        return "not_found"
    if not source.has_quote:
        return "url_verified"
    if (
        source.accepted
        and source.source_role != "background"
        and claim_role == "material"
        and quote_overlap >= MIN_SUPPORT_QUOTE_OVERLAP
    ):
        return "weak_support"
    return "passage_found"


def _explicit_verification_status(ref: EvidenceRef) -> str:
    provenance = ref.provenance or {}
    metadata = provenance.get("metadata") if isinstance(provenance.get("metadata"), dict) else {}
    return str(provenance.get("verification_status") or metadata.get("verification_status") or "").strip().casefold()


def _edge_claim_type(finding: Finding, verification_status: str) -> str:
    if verification_status == "directly_supports_claim":
        return "source_says"
    if verification_status == "weak_support":
        return "inferred_from_source"
    if _is_hypothesis_claim(finding):
        return "model_hypothesis"
    return "unsupported"


def _claim_type_for_edges(finding: Finding, edges: Sequence[ClaimSupportEdge]) -> str:
    statuses = {edge.verification_status for edge in edges}
    if "directly_supports_claim" in statuses:
        return "source_says"
    if "weak_support" in statuses:
        return "inferred_from_source"
    if _is_hypothesis_claim(finding):
        return "model_hypothesis"
    return "unsupported"


def _is_hypothesis_claim(finding: Finding) -> bool:
    text = " ".join([finding.claim, *finding.limitations]).casefold()
    markers = (
        "hypothesis",
        "hypothesize",
        "may ",
        "might ",
        "could ",
        "suggests",
        "recommend",
        "proposal",
        "propose",
        "next step",
    )
    return any(marker in text for marker in markers)


def _verification_reason(verification_status: str, support_type: str) -> str:
    if verification_status == "directly_supports_claim":
        return "accepted material source has locator, passage, and sufficient quote overlap"
    if verification_status == "weak_support":
        return "passage is present but does not meet direct material support requirements"
    if verification_status == "passage_found":
        return "passage exists, but it does not support this claim"
    if verification_status == "url_verified":
        return "source locator exists, but no cited passage was found"
    if verification_status == "contradiction":
        return "source passage contradicts the claim"
    return f"citation not found or incomplete: {support_type}"


def _uncertainty_entries(claim_entries: Sequence[ClaimLedgerEntry]) -> list[UncertaintyLedgerEntry]:
    rows: list[UncertaintyLedgerEntry] = []
    for claim in claim_entries:
        texts = [item for item in claim.limitations if item.strip()]
        if claim.claim_role == "uncertainty" and not texts:
            texts = [claim.claim]
        for offset, text in enumerate(texts, start=1):
            normalized = text.casefold()
            conflict = any(marker in normalized for marker in ("conflict", "contradict", "disagree", "상충", "충돌"))
            rows.append(
                UncertaintyLedgerEntry(
                    id=f"uncertainty-{len(rows) + 1:03d}",
                    text=text,
                    status="unresolved",
                    source_ids=tuple(edge.source_id for edge in claim.support_edges),
                    conflict=conflict,
                    disclosed=True,
                )
            )
    return rows


def _expected_claim_traceability(
    findings: Sequence[Finding],
    source_by_id: Mapping[str, SourceLedgerEntry],
    expected_claims: Sequence[Any],
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for expected in expected_claims:
        expected_id = str(getattr(expected, "id", "") or "").strip()
        required_terms = {
            _normalize_term(term)
            for term in getattr(expected, "required_terms", ())
            if _normalize_term(term)
        }
        min_matched = int(getattr(expected, "min_matched_terms", 1) or 1)
        supporting_edges: list[dict[str, Any]] = []
        for finding_index, finding in enumerate(findings, start=1):
            claim_role = _claim_role(finding)
            for ref in finding.support:
                source = source_by_id.get(ref.id)
                edge = _support_edge(f"claim-{finding_index:03d}", finding, ref, source, claim_role)
                if not edge.supported:
                    continue
                edge_terms = _terms(" ".join([finding.claim, str(ref.source_title or ""), str(ref.quote or "")]))
                matched = sorted(required_terms & edge_terms)
                if len(matched) >= min_matched:
                    supporting_edges.append(
                        {
                            "claim_id": f"claim-{finding_index:03d}",
                            "source_id": ref.id,
                            "matched_terms": matched,
                        }
                    )
        out[expected_id] = {
            "supported": bool(supporting_edges),
            "support_edge_count": len(supporting_edges),
            "support_edges": supporting_edges,
        }
    return out


def _contradiction_disclosures(claim_entries: Sequence[ClaimLedgerEntry]) -> tuple[dict[str, Any], ...]:
    disclosures: list[dict[str, Any]] = []
    for claim in claim_entries:
        if claim.claim_role != "material":
            continue
        source_ids = [edge.source_id for edge in claim.support_edges if edge.contradiction]
        if not source_ids:
            continue
        disclosures.append(
            {
                "claim_id": claim.id,
                "claim": claim.claim,
                "source_ids": source_ids,
                "readiness_impact": "needs_review",
                "disclosure": "material claim has unresolved contradictory evidence",
            }
        )
    return tuple(disclosures)


def _metrics(
    sources: Sequence[SourceLedgerEntry],
    claims: Sequence[ClaimLedgerEntry],
    uncertainties: Sequence[UncertaintyLedgerEntry],
    expected_traceability: Mapping[str, Mapping[str, Any]],
) -> dict[str, float]:
    material = [claim for claim in claims if claim.claim_role == "material"]
    material_supported = [claim for claim in material if claim.has_accepted_support]
    accepted_sources = [source for source in sources if source.accepted]
    quote_locator_count = sum(1 for source in accepted_sources if source.has_quote and source.has_locator)
    edges = [edge for claim in claims for edge in claim.support_edges]
    integral_edges = [edge for edge in edges if edge.supported and edge.has_quote and edge.has_locator]
    claim_type_counts = _claim_type_counts(claims)
    citation_status_counts = _citation_status_counts(edges)
    leaks = [
        edge
        for claim in material
        for edge in claim.support_edges
        if edge.support_type in {"background", "rejected"}
    ]
    high_conf_unsupported = [
        claim for claim in material if claim.confidence >= 0.75 and not claim.has_accepted_support
    ]
    conflicts = [entry for entry in uncertainties if entry.conflict]
    disclosed_conflicts = [entry for entry in conflicts if entry.disclosed]
    material_contradiction_claims = [
        claim
        for claim in material
        if any(edge.contradiction for edge in claim.support_edges)
    ]
    disclosed_material_contradictions = material_contradiction_claims
    expected_total = len(expected_traceability)
    expected_supported = sum(1 for row in expected_traceability.values() if row.get("supported"))
    expected_gap_count = max(0, expected_total - expected_supported)
    metrics = {
        "material_claim_support_coverage": _ratio(len(material_supported), len(material)),
        "expected_claim_traceability_score": _ratio(expected_supported, expected_total),
        "expected_claim_count": float(expected_total),
        "expected_claim_gap_count": float(expected_gap_count),
        "quote_locator_coverage": _ratio(quote_locator_count, len(accepted_sources)),
        "citation_integrity_score": _ratio(len(integral_edges), len(edges)),
        "background_leak_count": float(len(leaks)),
        "unsupported_high_confidence_claim_count": float(len(high_conf_unsupported)),
        "unresolved_conflict_count": float(len(conflicts)),
        "unresolved_conflict_disclosure_rate": _ratio(len(disclosed_conflicts), len(conflicts), empty=1.0),
        "material_contradiction_count": float(len(material_contradiction_claims)),
        "material_contradiction_disclosure_rate": _ratio(
            len(disclosed_material_contradictions),
            len(material_contradiction_claims),
            empty=1.0,
        ),
    }
    for claim_type in ("source_says", "inferred_from_source", "model_hypothesis", "unsupported"):
        metrics[f"claim_type.{claim_type}_count"] = float(claim_type_counts.get(claim_type, 0))
    for status in ("directly_supports_claim", "weak_support", "passage_found", "url_verified", "contradiction", "not_found"):
        metric_key = "direct_support" if status == "directly_supports_claim" else status
        metrics[f"citation.{metric_key}_count"] = float(citation_status_counts.get(status, 0))
    metrics["citation.direct_support_rate"] = _ratio(
        citation_status_counts.get("directly_supports_claim", 0),
        len(edges),
    )
    return metrics


def _claim_type_counts(claims: Sequence[ClaimLedgerEntry]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for claim in claims:
        counts[claim.claim_type] = counts.get(claim.claim_type, 0) + 1
    return counts


def _citation_status_counts(edges: Sequence[ClaimSupportEdge]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for edge in edges:
        counts[edge.verification_status] = counts.get(edge.verification_status, 0) + 1
    return counts


def _quality_gate_events(
    metrics: Mapping[str, float],
    *,
    contradiction_disclosures: Sequence[Mapping[str, Any]] = (),
) -> tuple[dict[str, Any], ...]:
    events = [
        {"event": "research_progress", "stage": "quality_gate", "status": "evidence_ledger_built", "metrics": dict(metrics)},
        {"event": "research_progress", "stage": "quality_gate", "status": "claim_traceability_scored", "metrics": dict(metrics)},
        {"event": "research_progress", "stage": "quality_gate", "status": "uncertainty_ledger_built", "metrics": dict(metrics)},
    ]
    if contradiction_disclosures:
        events.append(
            {
                "event": "research_progress",
                "stage": "quality_gate",
                "status": "contradiction_disclosure_built",
                "readiness_impact": "needs_review",
                "metrics": dict(metrics),
                "contradictions": [dict(item) for item in contradiction_disclosures],
            }
        )
    return tuple(events)


def _readiness(metrics: Mapping[str, float]) -> str:
    if float(metrics.get("expected_claim_gap_count", 0.0)) > 0:
        return "needs_review"
    if float(metrics.get("background_leak_count", 0.0)) > 0:
        return "needs_review"
    if float(metrics.get("unsupported_high_confidence_claim_count", 0.0)) > 0:
        return "needs_review"
    if float(metrics.get("unresolved_conflict_count", 0.0)) > 0:
        return "needs_review"
    if float(metrics.get("material_contradiction_count", 0.0)) > 0:
        return "needs_review"
    if float(metrics.get("unresolved_conflict_disclosure_rate", 1.0)) < 1.0:
        return "needs_review"
    if float(metrics.get("citation_integrity_score", 0.0)) < 0.8:
        return "needs_review"
    return "ready"


def _claim_role(finding: Finding) -> str:
    provenance_roles = [
        str((ref.provenance or {}).get("claim_role") or "").strip().casefold()
        for ref in finding.support
    ]
    if any(role in {"background", "material", "uncertainty"} for role in provenance_roles):
        return next(role for role in provenance_roles if role in {"background", "material", "uncertainty"})
    if _is_metadata_only_publication_claim(finding.claim):
        return "background"
    text = " ".join([finding.claim, *finding.limitations]).casefold()
    if any(marker in text for marker in ("uncertain", "unclear", "unknown", "gap", "conflict", "상충", "불확실")):
        return "uncertainty"
    return "material"


def _is_metadata_only_publication_claim(claim: str) -> bool:
    normalized = str(claim or "").casefold()
    if not any(marker in normalized for marker in ("published", "publication", "retrieved", "accessed", "updated", "date")):
        return False
    metadata_terms = {
        "access",
        "accessed",
        "at",
        "date",
        "day",
        "fetched",
        "in",
        "last",
        "metadata",
        "month",
        "on",
        "publication",
        "published",
        "retrieval",
        "retrieved",
        "source",
        "updated",
        "year",
    }
    substantive_terms = {
        term
        for term in _terms(normalized)
        if term not in metadata_terms and not term.isdigit()
    }
    return not substantive_terms


def _accepted(
    ref: EvidenceRef,
    source_kind: str,
    source_role: str,
    *,
    accepted_source_ids: set[str] | None = None,
) -> bool:
    if accepted_source_ids is not None:
        return ref.id in accepted_source_ids
    provenance = ref.provenance or {}
    metadata = provenance.get("metadata") if isinstance(provenance.get("metadata"), dict) else {}
    if "accepted" in provenance:
        return bool(provenance.get("accepted"))
    if "accepted" in metadata:
        return bool(metadata.get("accepted"))
    status = str(ref.access_status or provenance.get("status") or metadata.get("status") or "").casefold()
    if status in {"rejected", "blocked", "invalid"}:
        return False
    if str(ref.source_grade or "").upper() == "D":
        return False
    if source_kind in {"mock", "empty", "generated"}:
        return False
    return True


def _source_kind(ref: EvidenceRef) -> str:
    provenance = ref.provenance or {}
    metadata = provenance.get("metadata") if isinstance(provenance.get("metadata"), dict) else {}
    raw_kind = str(provenance.get("kind") or metadata.get("kind") or "").strip().casefold()
    url = str(ref.source_url or "").casefold()
    title = str(ref.source_title or "").casefold()
    text = f"{raw_kind} {url} {title}"
    if raw_kind:
        return raw_kind
    if "doi.org/" in url:
        return "doi"
    if any(marker in text for marker in ("government", ".gov", "ministry")):
        return "government"
    return "web"


def _default_source_role(source_kind: str) -> str:
    if source_kind in {"mock", "empty", "generated"}:
        return "background"
    return "primary"


def _default_authority_level(grade: str, source_kind: str) -> str:
    if str(grade or "").upper() == "A" or source_kind in {"doi", "academic", "crossref", "pubmed", "semantic_scholar"}:
        return "high"
    if str(grade or "").upper() == "B":
        return "medium"
    return "low"


def _default_rejection_reason(ref: EvidenceRef, source_kind: str, source_role: str) -> str:
    if str(ref.source_grade or "").upper() == "D":
        return "D-grade source cannot support material claims"
    if source_kind in {"mock", "empty", "generated"}:
        return f"{source_kind} source cannot support material claims"
    if source_role == "background":
        return "background source is context-only"
    return "source audit did not accept this reference"


def _claim_quote_overlap(claim: str, ref: EvidenceRef) -> float:
    claim_terms = _terms(claim)
    quote_terms = _terms(" ".join([str(ref.source_title or ""), str(ref.quote or "")]))
    if not claim_terms:
        return 0.0
    return round(len(claim_terms & quote_terms) / max(1, min(len(claim_terms), 8)), 3)


def _ratio(numerator: int, denominator: int, *, empty: float = 0.0) -> float:
    if denominator <= 0:
        return empty
    return round(numerator / denominator, 3)


def _terms(text: str) -> set[str]:
    raw = re.findall(r"[A-Za-z0-9]+|[가-힣]{2,}", str(text or ""))
    return {term for term in (_normalize_term(item) for item in raw) if term}


def _normalize_term(term: Any) -> str:
    value = str(term or "").strip().casefold()
    if value.endswith("ies") and len(value) > 4:
        return value[:-3] + "y"
    if value.endswith("s") and len(value) > 3:
        return value[:-1]
    return value


def _clean_token(value: Any) -> str:
    token = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
    return token or "unknown"
