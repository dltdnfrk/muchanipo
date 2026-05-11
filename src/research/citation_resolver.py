"""Deterministic canonical citation resolver for research source identity.

This module is offline-first and domain-neutral. It normalizes stable public
identifiers when they are present and marks redirect/listing wrappers as not
usable for material support until a canonical target is available.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", re.IGNORECASE)
_PMID_RE = re.compile(r"\b(?:pmid[:\s]*|pubmed/(?:\w+/)?)(\d{5,10})\b", re.IGNORECASE)
_PMCID_RE = re.compile(r"\b(PMC\d{5,10})\b", re.IGNORECASE)
_ARXIV_RE = re.compile(r"\b(?:arxiv[:/\s]*)(\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?)\b", re.IGNORECASE)
_PATENT_RE = re.compile(r"\b((?:US|EP|WO|CN|JP|KR)\s?\d{4,}[A-Z0-9]*)\b", re.IGNORECASE)
_TRIAL_RE = re.compile(r"\b(NCT\d{8})\b", re.IGNORECASE)

_REDIRECT_HOST_MARKERS = (
    "vertexaisearch.cloud.google.com",
    "google.com",
    "googleusercontent.com",
    "search.google.com",
)
_REDIRECT_PATH_MARKERS = (
    "grounding-api-redirect",
    "/url",
    "redirect",
)
_WEAK_HOST_MARKERS = (
    "researchgate.net",
    "grokipedia",
    "wikipedia.org",
)
_WEAK_PATH_MARKERS = (
    "search",
    "results",
    "browse",
    "topics",
)


@dataclass(frozen=True)
class CitationCandidate:
    source_id: str
    title: str
    url: str
    quote: str = ""
    source_class: str = ""
    route_id: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class ResolvedCitation:
    source_id: str
    canonical_id: str | None
    canonical_url: str | None
    identifier_kind: str
    normalized_title: str
    redirect_chain: tuple[str, ...]
    resolver_status: str
    needs_review_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "canonical_id": self.canonical_id,
            "canonical_url": self.canonical_url,
            "identifier_kind": self.identifier_kind,
            "normalized_title": self.normalized_title,
            "redirect_chain": list(self.redirect_chain),
            "resolver_status": self.resolver_status,
            "needs_review_reason": self.needs_review_reason,
        }


def resolve_citation(candidate: CitationCandidate) -> ResolvedCitation:
    """Resolve a source candidate to a stable canonical identifier when possible."""

    title = str(candidate.title or "")
    url = str(candidate.url or "")
    metadata = candidate.metadata or {}
    combined = " ".join(
        part
        for part in (
            title,
            url,
            str(metadata.get("doi") or ""),
            str(metadata.get("pmid") or ""),
            str(metadata.get("pmcid") or ""),
            str(metadata.get("arxiv") or ""),
        )
        if part
    )
    normalized_title = _normalize_title(title)
    redirect_chain = _redirect_chain(url)

    if _is_redirect_only(url):
        embedded_target = _embedded_redirect_target(url)
        if embedded_target:
            nested = resolve_citation(
                CitationCandidate(
                    source_id=candidate.source_id,
                    title=title,
                    url=embedded_target,
                    quote=candidate.quote,
                    source_class=candidate.source_class,
                    route_id=candidate.route_id,
                    metadata=metadata,
                )
            )
            return ResolvedCitation(
                source_id=candidate.source_id,
                canonical_id=nested.canonical_id,
                canonical_url=nested.canonical_url,
                identifier_kind=nested.identifier_kind,
                normalized_title=normalized_title,
                redirect_chain=tuple([url, *nested.redirect_chain]),
                resolver_status=nested.resolver_status,
                needs_review_reason=nested.needs_review_reason,
            )
        return ResolvedCitation(
            source_id=candidate.source_id,
            canonical_id=None,
            canonical_url=None,
            identifier_kind="unknown",
            normalized_title=normalized_title,
            redirect_chain=redirect_chain,
            resolver_status="redirect_only",
            needs_review_reason="redirect-only wrapper lacks canonical target metadata",
        )

    doi = _extract_doi(combined)
    if doi:
        return ResolvedCitation(
            source_id=candidate.source_id,
            canonical_id=doi,
            canonical_url=f"https://doi.org/{doi}",
            identifier_kind="doi",
            normalized_title=normalized_title,
            redirect_chain=redirect_chain,
            resolver_status="resolved",
        )

    pmcid = _extract_first(_PMCID_RE, combined)
    if pmcid:
        normalized = pmcid.upper()
        return ResolvedCitation(candidate.source_id, normalized, f"https://www.ncbi.nlm.nih.gov/pmc/articles/{normalized}/", "pmcid", normalized_title, redirect_chain, "resolved")

    pmid = _extract_pmid(combined)
    if pmid:
        return ResolvedCitation(candidate.source_id, pmid, f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", "pmid", normalized_title, redirect_chain, "resolved")

    arxiv = _extract_arxiv(combined)
    if arxiv:
        return ResolvedCitation(candidate.source_id, arxiv, f"https://arxiv.org/abs/{arxiv}", "arxiv", normalized_title, redirect_chain, "resolved")

    trial = _extract_first(_TRIAL_RE, combined)
    if trial:
        trial = trial.upper()
        return ResolvedCitation(candidate.source_id, trial, f"https://clinicaltrials.gov/study/{trial}", "trial", normalized_title, redirect_chain, "resolved")

    patent = _extract_first(_PATENT_RE, combined)
    if patent:
        canonical = re.sub(r"\s+", "", patent.upper())
        return ResolvedCitation(candidate.source_id, canonical, None, "patent", normalized_title, redirect_chain, "resolved")

    if _is_weak_or_listing(url):
        return ResolvedCitation(
            source_id=candidate.source_id,
            canonical_id=None,
            canonical_url=None,
            identifier_kind="url" if url else "unknown",
            normalized_title=normalized_title,
            redirect_chain=redirect_chain,
            resolver_status="unsupported",
            needs_review_reason="weak source or listing page is not stable material evidence",
        )

    canonical_url = _canonical_url(url)
    if canonical_url:
        return ResolvedCitation(
            source_id=candidate.source_id,
            canonical_id=canonical_url,
            canonical_url=canonical_url,
            identifier_kind="url",
            normalized_title=normalized_title,
            redirect_chain=redirect_chain,
            resolver_status="resolved",
        )

    return ResolvedCitation(
        source_id=candidate.source_id,
        canonical_id=None,
        canonical_url=None,
        identifier_kind="unknown",
        normalized_title=normalized_title,
        redirect_chain=redirect_chain,
        resolver_status="unresolved",
        needs_review_reason="no stable identifier or canonical URL found",
    )


def _extract_doi(text: str) -> str | None:
    match = _DOI_RE.search(text or "")
    if not match:
        return None
    doi = unquote(match.group(1)).strip().lower()
    doi = doi.split("?")[0].split("#")[0]
    return doi.rstrip(".,;)\"]'}")


def _extract_pmid(text: str) -> str | None:
    explicit = _extract_first(_PMID_RE, text)
    if explicit:
        return explicit
    parsed = urlparse(text if "://" in text else "")
    if "pubmed.ncbi.nlm.nih.gov" in parsed.netloc:
        for part in parsed.path.split("/"):
            if part.isdigit() and 5 <= len(part) <= 10:
                return part
    return None


def _extract_arxiv(text: str) -> str | None:
    match = _ARXIV_RE.search(text or "")
    if match:
        return match.group(1).lower()
    parsed = urlparse(text if "://" in text else "")
    if "arxiv.org" in parsed.netloc and "/abs/" in parsed.path:
        return parsed.path.rsplit("/", 1)[-1].lower()
    return None


def _extract_first(regex: re.Pattern[str], text: str) -> str | None:
    match = regex.search(text or "")
    return match.group(1) if match else None


def _is_redirect_only(url: str) -> bool:
    parsed = urlparse(url or "")
    host = parsed.netloc.casefold()
    path = parsed.path.casefold()
    if not host:
        return False
    if "grounding-api-redirect" in path:
        return True
    if any(marker in host for marker in _REDIRECT_HOST_MARKERS) and any(marker in path for marker in _REDIRECT_PATH_MARKERS):
        return True
    return False


def _embedded_redirect_target(url: str) -> str | None:
    parsed = urlparse(url or "")
    params = parse_qs(parsed.query)
    for key in ("url", "q", "target", "redirect"):
        values = params.get(key) or []
        for value in values:
            value = unquote(value)
            if value.startswith(("http://", "https://")):
                return value
    return None


def _redirect_chain(url: str) -> tuple[str, ...]:
    url = str(url or "").strip()
    return (url,) if url else ()


def _is_weak_or_listing(url: str) -> bool:
    parsed = urlparse(url or "")
    host = parsed.netloc.casefold()
    path = parsed.path.casefold().strip("/")
    query = parsed.query.casefold()
    if any(marker in host for marker in _WEAK_HOST_MARKERS):
        return True
    if any(part == path or path.endswith(f"/{part}") for part in _WEAK_PATH_MARKERS):
        return True
    if any(marker in query for marker in ("search=", "query=", "q=")) and any(marker in path for marker in _WEAK_PATH_MARKERS):
        return True
    return False


def _canonical_url(url: str) -> str | None:
    parsed = urlparse(url or "")
    if not parsed.scheme or not parsed.netloc:
        return None
    scheme = "https" if parsed.scheme in {"http", "https"} else parsed.scheme
    host = parsed.netloc.casefold()
    path = parsed.path.rstrip("/") or "/"
    return f"{scheme}://{host}{path}"


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", str(title or "").strip()).casefold()
