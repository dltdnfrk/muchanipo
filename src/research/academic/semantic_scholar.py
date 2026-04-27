"""Semantic Scholar academic search integration."""
from __future__ import annotations

import os
from typing import Any

import httpx

from src.evidence.artifact import EvidenceRef

from .common import AcademicHttpClient, compact_text, evidence_ref, normalize_doi, source_grade_for_paper


SEMANTIC_SCHOLAR_BASE_URL = "https://api.semanticscholar.org/graph/v1"
PAPER_FIELDS = "paperId,title,abstract,url,year,authors,citationCount,externalIds"


class SemanticScholarClient:
    """Async Semantic Scholar client with conservative unauthenticated limits."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        api_key: str | None = None,
        min_interval_seconds: float = 1.0,
    ) -> None:
        token = api_key or os.getenv("SEMANTIC_SCHOLAR_API_KEY")
        headers = {"x-api-key": token} if token else {}
        self.http = AcademicHttpClient(
            base_url=SEMANTIC_SCHOLAR_BASE_URL,
            headers=headers,
            max_concurrency=1,
            min_interval_seconds=min_interval_seconds,
            client=client,
        )

    async def aclose(self) -> None:
        await self.http.aclose()

    async def search(self, query: str, limit: int = 10, **kwargs: Any) -> list[EvidenceRef]:
        data = await self.http.get_json(
            "/paper/search",
            params={"query": query, "limit": limit, "fields": PAPER_FIELDS, **kwargs},
        )
        return [self._to_evidence(item) for item in data.get("data", [])]

    async def get_paper(self, paper_id: str) -> EvidenceRef | None:
        data = await self.http.get_json(f"/paper/{paper_id}", params={"fields": PAPER_FIELDS})
        return self._to_evidence(data) if data else None

    async def get_citations(self, paper_id: str, limit: int = 50) -> list[EvidenceRef]:
        data = await self.http.get_json(
            f"/paper/{paper_id}/citations",
            params={"limit": limit, "fields": f"citingPaper.{PAPER_FIELDS}"},
        )
        papers = [item.get("citingPaper") for item in data.get("data", [])]
        return [self._to_evidence(item) for item in papers if isinstance(item, dict)]

    def _to_evidence(self, item: dict[str, Any]) -> EvidenceRef:
        paper_id = str(item.get("paperId") or item.get("url") or item.get("title") or "unknown")
        external_ids = item.get("externalIds") or {}
        doi = normalize_doi(external_ids.get("DOI"))
        quote = compact_text([item.get("abstract"), item.get("year"), f"citations={item.get('citationCount')}"])
        return evidence_ref(
            source="semantic_scholar",
            paper_id=paper_id,
            raw=item,
            source_url=item.get("url") or (f"https://doi.org/{doi}" if doi else None),
            source_title=item.get("title"),
            quote=quote,
            source_grade=source_grade_for_paper(doi=doi),
        )


async def search(query: str, limit: int = 10, **kwargs: Any) -> list[EvidenceRef]:
    client = SemanticScholarClient()
    try:
        return await client.search(query, limit, **kwargs)
    finally:
        await client.aclose()


async def get_paper(paper_id: str) -> EvidenceRef | None:
    client = SemanticScholarClient()
    try:
        return await client.get_paper(paper_id)
    finally:
        await client.aclose()


async def get_citations(paper_id: str, limit: int = 50) -> list[EvidenceRef]:
    client = SemanticScholarClient()
    try:
        return await client.get_citations(paper_id, limit)
    finally:
        await client.aclose()
