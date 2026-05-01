"""Unpaywall open-access lookup integration."""
from __future__ import annotations

from typing import Any

import httpx

from src.evidence.artifact import EvidenceRef

from .common import AcademicHttpClient, compact_text, contact_email, evidence_ref, normalize_doi, source_grade_for_paper


UNPAYWALL_BASE_URL = "https://api.unpaywall.org"


class UnpaywallClient:
    """Async Unpaywall client for DOI-to-open-access resolution."""

    def __init__(self, *, client: httpx.AsyncClient | None = None, email: str | None = None) -> None:
        self.email = email or contact_email()
        self.http = AcademicHttpClient(
            base_url=UNPAYWALL_BASE_URL,
            headers={"User-Agent": f"muchanipo/0.1 (mailto:{self.email})"},
            max_concurrency=10,
            client=client,
        )

    async def aclose(self) -> None:
        await self.http.aclose()

    async def search(self, query: str, limit: int = 10, **kwargs: Any) -> list[EvidenceRef]:
        data = await self.http.get_json(
            "/v2/search",
            params={"query": query, "email": self.email, "limit": limit, **kwargs},
        )
        raw_results = data.get("results", []) if isinstance(data, dict) else []
        papers = []
        for item in raw_results:
            if isinstance(item, dict):
                response = item.get("response")
                papers.append(response if isinstance(response, dict) else item)
        return [self._to_evidence(item) for item in papers]

    async def get_paper(self, paper_id: str) -> EvidenceRef | None:
        doi = normalize_doi(paper_id) or paper_id
        data = await self.http.get_json(f"/v2/{doi}", params={"email": self.email})
        return self._to_evidence(data) if data else None

    async def get_citations(self, paper_id: str, limit: int = 50) -> list[EvidenceRef]:
        return []

    def _to_evidence(self, item: dict[str, Any]) -> EvidenceRef:
        doi = normalize_doi(item.get("doi"))
        paper_id = doi or str(item.get("title") or "unknown")
        oa_location = item.get("best_oa_location") or {}
        source_url = (
            oa_location.get("url_for_pdf")
            or oa_location.get("url")
            or item.get("doi_url")
            or (f"https://doi.org/{doi}" if doi else None)
        )
        quote = compact_text([item.get("title"), item.get("journal_name"), item.get("year"), item.get("is_oa")])
        return evidence_ref(
            source="unpaywall",
            paper_id=paper_id,
            raw=item,
            source_url=source_url,
            source_title=item.get("title"),
            quote=quote,
            source_grade=source_grade_for_paper(doi=doi),
            doi=doi,
            journal=item.get("journal_name"),
        )


async def search(query: str, limit: int = 10, **kwargs: Any) -> list[EvidenceRef]:
    client = UnpaywallClient()
    try:
        return await client.search(query, limit, **kwargs)
    finally:
        await client.aclose()


async def get_paper(paper_id: str) -> EvidenceRef | None:
    client = UnpaywallClient()
    try:
        return await client.get_paper(paper_id)
    finally:
        await client.aclose()


async def get_citations(paper_id: str, limit: int = 50) -> list[EvidenceRef]:
    client = UnpaywallClient()
    try:
        return await client.get_citations(paper_id, limit)
    finally:
        await client.aclose()
