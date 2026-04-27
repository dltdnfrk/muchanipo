"""OpenAlex academic search integration."""
from __future__ import annotations

from typing import Any

import httpx

from src.evidence.artifact import EvidenceRef

from .common import AcademicHttpClient, compact_text, contact_email, evidence_ref, normalize_doi, source_grade_for_paper


OPENALEX_BASE_URL = "https://api.openalex.org"


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
        )


def _abstract_from_inverted_index(index: dict[str, list[int]] | None) -> str | None:
    if not index:
        return None
    words: list[tuple[int, str]] = []
    for word, positions in index.items():
        words.extend((position, word) for position in positions)
    return " ".join(word for _, word in sorted(words)) or None


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
