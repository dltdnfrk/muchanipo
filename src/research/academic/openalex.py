"""OpenAlex academic search integration."""
from __future__ import annotations

import os
from typing import Any

import httpx

from src.evidence.artifact import EvidenceRef

from .common import AcademicHttpClient, compact_text, contact_email, evidence_ref, normalize_doi, source_grade_for_paper


OPENALEX_BASE_URL = "https://api.openalex.org"
OPENALEX_TARGETING_TIMEOUT_SEC = 5.0


class OpenAlexClient:
    """Async OpenAlex client with polite-pool contact metadata."""

    def __init__(self, *, client: httpx.AsyncClient | None = None, email: str | None = None) -> None:
        self.email = email or contact_email()
        self.http = AcademicHttpClient(
            base_url=OPENALEX_BASE_URL,
            headers={
                "User-Agent": f"muchanipo/0.1 (mailto:{self.email})",
                "From": self.email,
            },
            max_concurrency=10,
            client=client,
        )

    async def aclose(self) -> None:
        await self.http.aclose()

    async def search(self, query: str, limit: int = 10, **kwargs: Any) -> list[EvidenceRef]:
        data = await self.http.get_json(
            "/works",
            params={
                "search": query,
                "per-page": limit,
                "mailto": self.email,
                **kwargs,
            },
        )
        return [self._to_evidence(item) for item in data.get("results", [])]

    async def get_paper(self, paper_id: str) -> EvidenceRef | None:
        data = await self.http.get_json(f"/works/{paper_id}", params={"mailto": self.email})
        return self._to_evidence(data) if data else None

    async def get_citations(self, paper_id: str, limit: int = 50) -> list[EvidenceRef]:
        openalex_id = paper_id.rsplit("/", 1)[-1]
        data = await self.http.get_json(
            "/works",
            params={
                "filter": f"cites:{openalex_id}",
                "per-page": limit,
                "mailto": self.email,
            },
        )
        return [self._to_evidence(item) for item in data.get("results", [])]

    def _to_evidence(self, item: dict[str, Any]) -> EvidenceRef:
        paper_id = str(item.get("id") or item.get("doi") or item.get("display_name") or "unknown")
        doi = normalize_doi(item.get("doi"))
        abstract = _abstract_from_inverted_index(item.get("abstract_inverted_index"))
        quote = compact_text([abstract, item.get("publication_year")])
        return evidence_ref(
            source="openalex",
            paper_id=paper_id,
            raw=item,
            source_url=item.get("doi") or item.get("id"),
            source_title=item.get("display_name"),
            quote=quote,
            source_grade=source_grade_for_paper(doi=doi),
            doi=doi,
            journal=_journal_name(item),
            institution=_institution_name(item),
        )


def _abstract_from_inverted_index(index: dict[str, list[int]] | None) -> str | None:
    if not index:
        return None
    words: list[tuple[int, str]] = []
    for word, positions in index.items():
        words.extend((position, word) for position in positions)
    return " ".join(word for _, word in sorted(words)) or None


def _journal_name(item: dict[str, Any]) -> str | None:
    primary_source = ((item.get("primary_location") or {}).get("source") or {})
    host_venue = item.get("host_venue") or {}
    return (
        primary_source.get("display_name")
        or primary_source.get("host_organization_name")
        or host_venue.get("display_name")
    )


def _institution_name(item: dict[str, Any]) -> str | None:
    for authorship in item.get("authorships") or []:
        if not isinstance(authorship, dict):
            continue
        for institution in authorship.get("institutions") or []:
            if isinstance(institution, dict) and institution.get("display_name"):
                return str(institution["display_name"])
    return None


async def search(query: str, limit: int = 10, **kwargs: Any) -> list[EvidenceRef]:
    client = OpenAlexClient()
    try:
        return await client.search(query, limit, **kwargs)
    finally:
        await client.aclose()


async def get_paper(paper_id: str) -> EvidenceRef | None:
    client = OpenAlexClient()
    try:
        return await client.get_paper(paper_id)
    finally:
        await client.aclose()


async def get_citations(paper_id: str, limit: int = 50) -> list[EvidenceRef]:
    client = OpenAlexClient()
    try:
        return await client.get_citations(paper_id, limit)
    finally:
        await client.aclose()


def query_institutions(domains: list[str], limit: int = 5) -> tuple[list[str], list[dict[str, Any]]]:
    """Return OpenAlex institutions for targeting-map construction."""
    return _query_targeting_names("/institutions", domains, limit=limit, field="display_name")


def query_journals(domains: list[str], limit: int = 5) -> tuple[list[str], list[dict[str, Any]]]:
    """Return OpenAlex journal/source names for targeting-map construction."""
    return _query_targeting_names("/sources", domains, limit=limit, field="display_name", filters="type:journal")


def query_seed_papers(domains: list[str], limit: int = 5) -> tuple[list[str], list[dict[str, Any]]]:
    """Return OpenAlex DOI/title seed papers for targeting-map construction."""
    return _query_targeting_names("/works", domains, limit=limit, field="doi_or_title")


def _query_targeting_names(
    endpoint: str,
    domains: list[str],
    *,
    limit: int,
    field: str,
    filters: str | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    if _skip_live_targeting():
        return [], [
            {
                "source": "openalex",
                "endpoint": endpoint,
                "status": "skipped",
                "reason": "disabled during pytest unless MUCHANIPO_ACADEMIC_TARGETING=1",
            }
        ]

    names: list[str] = []
    provenance: list[dict[str, Any]] = []
    seen: set[str] = set()
    safe_limit = max(1, limit)
    email = contact_email()
    with httpx.Client(
        base_url=OPENALEX_BASE_URL,
        headers={
            "User-Agent": f"muchanipo/0.1 (mailto:{email})",
            "From": email,
        },
        timeout=OPENALEX_TARGETING_TIMEOUT_SEC,
    ) as client:
        for domain in domains or ["general"]:
            params: dict[str, Any] = {
                "search": domain,
                "per-page": safe_limit,
                "mailto": email,
            }
            if filters:
                params["filter"] = filters
            try:
                response = client.get(endpoint, params=params)
                response.raise_for_status()
                payload = response.json()
            except Exception as exc:  # noqa: BLE001 - targeting must degrade gracefully
                provenance.append(
                    {
                        "source": "openalex",
                        "endpoint": endpoint,
                        "query": domain,
                        "status": "error",
                        "error": str(exc).splitlines()[0][:160],
                    }
                )
                continue
            results = payload.get("results", []) if isinstance(payload, dict) else []
            for item in results:
                if not isinstance(item, dict):
                    continue
                name = _targeting_name(item, field=field)
                if not name or name in seen:
                    continue
                seen.add(name)
                names.append(name)
            provenance.append(
                {
                    "source": "openalex",
                    "endpoint": endpoint,
                    "query": domain,
                    "status": "ok",
                    "count": len(results),
                }
            )
    return names[:safe_limit], provenance


def _targeting_name(item: dict[str, Any], *, field: str) -> str:
    if field == "doi_or_title":
        return str(normalize_doi(item.get("doi")) or item.get("display_name") or "").strip()
    return str(item.get(field) or "").strip()


def _skip_live_targeting() -> bool:
    if os.environ.get("MUCHANIPO_ACADEMIC_TARGETING", "").strip().lower() in {"1", "true", "yes", "on"}:
        return False
    if os.environ.get("MUCHANIPO_ACADEMIC_TARGETING", "").strip().lower() in {"0", "false", "no", "off"}:
        return True
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))
