"""CrossRef metadata integration."""
from __future__ import annotations

from typing import Any

import httpx

from src.evidence.artifact import EvidenceRef

from .common import AcademicHttpClient, compact_text, contact_email, evidence_ref, normalize_doi, source_grade_for_paper


CROSSREF_BASE_URL = "https://api.crossref.org"


class CrossRefClient:
    """Async CrossRef client for DOI-centered metadata enrichment."""

    def __init__(self, *, client: httpx.AsyncClient | None = None, email: str | None = None) -> None:
        self.email = email or contact_email()
        self.http = AcademicHttpClient(
            base_url=CROSSREF_BASE_URL,
            headers={
                "User-Agent": f"muchanipo/0.1 (mailto:{self.email})",
                "From": self.email,
            },
            max_concurrency=50,
            client=client,
        )

    async def aclose(self) -> None:
        await self.http.aclose()

    async def search(self, query: str, limit: int = 10, **kwargs: Any) -> list[EvidenceRef]:
        data = await self.http.get_json(
            "/works",
            params={"query": query, "rows": limit, "mailto": self.email, **kwargs},
        )
        return [self._to_evidence(item) for item in data.get("message", {}).get("items", [])]

    async def get_paper(self, paper_id: str) -> EvidenceRef | None:
        doi = normalize_doi(paper_id) or paper_id
        data = await self.http.get_json(f"/works/{doi}", params={"mailto": self.email})
        item = data.get("message") if isinstance(data, dict) else None
        return self._to_evidence(item) if isinstance(item, dict) else None

    async def get_citations(self, paper_id: str, limit: int = 50) -> list[EvidenceRef]:
        return []

    def _to_evidence(self, item: dict[str, Any]) -> EvidenceRef:
        doi = normalize_doi(item.get("DOI"))
        paper_id = doi or str(item.get("URL") or item.get("title") or "unknown")
        title = _first(item.get("title"))
        abstract = item.get("abstract")
        published = item.get("published-print") or item.get("published-online") or item.get("created")
        quote = compact_text([abstract, _container_title(item), published])
        return evidence_ref(
            source="crossref",
            paper_id=paper_id,
            raw=item,
            source_url=item.get("URL") or (f"https://doi.org/{doi}" if doi else None),
            source_title=title,
            quote=quote,
            source_grade=source_grade_for_paper(doi=doi),
            doi=doi,
            journal=_container_title(item),
        )


def _first(value: Any) -> str | None:
    if isinstance(value, list) and value:
        return str(value[0])
    if value:
        return str(value)
    return None


def _container_title(item: dict[str, Any]) -> str | None:
    return _first(item.get("container-title"))


async def search(query: str, limit: int = 10, **kwargs: Any) -> list[EvidenceRef]:
    client = CrossRefClient()
    try:
        return await client.search(query, limit, **kwargs)
    finally:
        await client.aclose()


async def get_paper(paper_id: str) -> EvidenceRef | None:
    client = CrossRefClient()
    try:
        return await client.get_paper(paper_id)
    finally:
        await client.aclose()


async def get_citations(paper_id: str, limit: int = 50) -> list[EvidenceRef]:
    client = CrossRefClient()
    try:
        return await client.get_citations(paper_id, limit)
    finally:
        await client.aclose()
