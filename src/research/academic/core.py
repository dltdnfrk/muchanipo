"""CORE academic full-text aggregator integration."""
from __future__ import annotations

import os
from typing import Any

import httpx

from src.evidence.artifact import EvidenceRef

from .common import AcademicHttpClient, compact_text, evidence_ref, normalize_doi, source_grade_for_paper


CORE_BASE_URL = "https://api.core.ac.uk/v3"


class CoreClient:
    """Async CORE client for full-text-oriented academic discovery."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        api_key: str | None = None,
        min_interval_seconds: float = 1.25,
    ) -> None:
        token = api_key or os.getenv("CORE_API_KEY")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.http = AcademicHttpClient(
            base_url=CORE_BASE_URL,
            headers=headers,
            max_concurrency=5,
            min_interval_seconds=min_interval_seconds,
            client=client,
        )

    async def aclose(self) -> None:
        await self.http.aclose()

    async def search(self, query: str, limit: int = 10, **kwargs: Any) -> list[EvidenceRef]:
        data = await self.http.get_json(
            "/search/works",
            params={"q": query, "limit": limit, **kwargs},
        )
        return [self._to_evidence(item) for item in data.get("results", [])]

    async def get_paper(self, paper_id: str) -> EvidenceRef | None:
        data = await self.http.get_json(f"/works/{paper_id}")
        return self._to_evidence(data) if data else None

    async def get_citations(self, paper_id: str, limit: int = 50) -> list[EvidenceRef]:
        return []

    def _to_evidence(self, item: dict[str, Any]) -> EvidenceRef:
        paper_id = str(item.get("id") or item.get("doi") or item.get("title") or "unknown")
        doi = normalize_doi(item.get("doi"))
        source_url = item.get("downloadUrl") or item.get("fullTextLink") or item.get("doi")
        quote = compact_text([item.get("abstract"), item.get("fullText")])
        return evidence_ref(
            source="core",
            paper_id=paper_id,
            raw=item,
            source_url=source_url,
            source_title=item.get("title"),
            quote=quote,
            source_grade=source_grade_for_paper(doi=doi),
        )


async def search(query: str, limit: int = 10, **kwargs: Any) -> list[EvidenceRef]:
    client = CoreClient()
    try:
        return await client.search(query, limit, **kwargs)
    finally:
        await client.aclose()


async def get_paper(paper_id: str) -> EvidenceRef | None:
    client = CoreClient()
    try:
        return await client.get_paper(paper_id)
    finally:
        await client.aclose()


async def get_citations(paper_id: str, limit: int = 50) -> list[EvidenceRef]:
    client = CoreClient()
    try:
        return await client.get_citations(paper_id, limit)
    finally:
        await client.aclose()
