import asyncio

import httpx

from src.research.academic.semantic_scholar import SemanticScholarClient


def test_semantic_scholar_search_sends_api_key_and_maps_evidence():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/graph/v1/paper/search"
        assert request.headers["x-api-key"] == "secret"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "paperId": "S2-1",
                        "title": "Citation Graphs",
                        "abstract": "Graph evidence",
                        "year": 2025,
                        "citationCount": 12,
                        "externalIds": {"DOI": "10.555/s2"},
                        "url": "https://semanticscholar.org/paper/S2-1",
                    }
                ]
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = SemanticScholarClient(client=http, api_key="secret", min_interval_seconds=0)
            return await client.search("citation graph")

    results = asyncio.run(run())

    assert results[0].id == "semantic_scholar:S2-1"
    assert results[0].source_grade == "A"
    assert results[0].provenance["doi"] == "10.555/s2"
    assert results[0].provenance["source_text"]["citationCount"] == 12


def test_semantic_scholar_citations_maps_citing_papers():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/graph/v1/paper/S2-1/citations"
        return httpx.Response(200, json={"data": [{"citingPaper": {"paperId": "S2-2", "title": "Follow up"}}]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = SemanticScholarClient(client=http, min_interval_seconds=0)
            return await client.get_citations("S2-1")

    results = asyncio.run(run())

    assert results[0].source_title == "Follow up"
