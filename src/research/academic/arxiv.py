"""arXiv preprint search integration."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

import httpx

from src.evidence.artifact import EvidenceRef

from .common import AcademicHttpClient, compact_text, evidence_ref


ARXIV_BASE_URL = "https://export.arxiv.org"
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


class ArxivClient:
    """Async arXiv client that defaults to the required 3-second delay."""

    def __init__(self, *, client: httpx.AsyncClient | None = None, min_interval_seconds: float = 3.0) -> None:
        self.http = AcademicHttpClient(
            base_url=ARXIV_BASE_URL,
            headers={"User-Agent": "muchanipo/0.1"},
            max_concurrency=1,
            min_interval_seconds=min_interval_seconds,
            client=client,
        )

    async def aclose(self) -> None:
        await self.http.aclose()

    async def search(self, query: str, limit: int = 10, **kwargs: Any) -> list[EvidenceRef]:
        response = await self.http.get(
            "/api/query",
            params={"search_query": query, "start": 0, "max_results": limit, **kwargs},
        )
        return [self._to_evidence(entry) for entry in _entries(response.text)]

    async def get_paper(self, paper_id: str) -> EvidenceRef | None:
        response = await self.http.get("/api/query", params={"id_list": _strip_arxiv_url(paper_id)})
        entries = _entries(response.text)
        return self._to_evidence(entries[0]) if entries else None

    async def get_citations(self, paper_id: str, limit: int = 50) -> list[EvidenceRef]:
        return []

    def _to_evidence(self, entry: ET.Element) -> EvidenceRef:
        raw = _entry_to_raw(entry)
        paper_id = raw.get("id") or raw.get("title") or "unknown"
        quote = compact_text([raw.get("summary"), raw.get("published")])
        return evidence_ref(
            source="arxiv",
            paper_id=str(paper_id),
            raw=raw,
            source_url=raw.get("id"),
            source_title=raw.get("title"),
            quote=quote,
            source_grade="B",
        )


def _entries(atom_xml: str) -> list[ET.Element]:
    root = ET.fromstring(atom_xml)
    return list(root.findall("atom:entry", ATOM_NS))


def _text(entry: ET.Element, tag: str) -> str | None:
    child = entry.find(f"atom:{tag}", ATOM_NS)
    if child is None or child.text is None:
        return None
    return " ".join(child.text.split())


def _entry_to_raw(entry: ET.Element) -> dict[str, Any]:
    return {
        "id": _text(entry, "id"),
        "title": _text(entry, "title"),
        "summary": _text(entry, "summary"),
        "published": _text(entry, "published"),
        "updated": _text(entry, "updated"),
        "authors": [_text(author, "name") for author in entry.findall("atom:author", ATOM_NS)],
        "raw_entry_xml": ET.tostring(entry, encoding="unicode"),
    }


def _strip_arxiv_url(paper_id: str) -> str:
    return paper_id.rstrip("/").rsplit("/", 1)[-1]


async def search(query: str, limit: int = 10, **kwargs: Any) -> list[EvidenceRef]:
    client = ArxivClient()
    try:
        return await client.search(query, limit, **kwargs)
    finally:
        await client.aclose()


async def get_paper(paper_id: str) -> EvidenceRef | None:
    client = ArxivClient()
    try:
        return await client.get_paper(paper_id)
    finally:
        await client.aclose()


async def get_citations(paper_id: str, limit: int = 50) -> list[EvidenceRef]:
    client = ArxivClient()
    try:
        return await client.get_citations(paper_id, limit)
    finally:
        await client.aclose()
