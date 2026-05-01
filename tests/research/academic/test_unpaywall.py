import asyncio

import httpx

from src.research.academic.unpaywall import UnpaywallClient


def test_unpaywall_get_paper_requires_email_and_maps_oa_location():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/10.1000/oa"
        assert request.url.params["email"] == "dev@example.com"
        return httpx.Response(
            200,
            json={
                "doi": "10.1000/oa",
                "doi_url": "https://doi.org/10.1000/oa",
                "title": "Open access paper",
                "journal_name": "OA Journal",
                "year": 2024,
                "is_oa": True,
                "best_oa_location": {"url_for_pdf": "https://example.com/paper.pdf"},
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = UnpaywallClient(client=http, email="dev@example.com")
            return await client.get_paper("doi:10.1000/oa")

    result = asyncio.run(run())

    assert result is not None
    assert result.id == "unpaywall:10.1000/oa"
    assert result.source_url == "https://example.com/paper.pdf"
    assert result.provenance["doi"] == "10.1000/oa"
    assert result.provenance["journal"] == "OA Journal"
    assert result.provenance["source_text"]["is_oa"] is True


def test_unpaywall_search_maps_response_wrappers():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/search"
        return httpx.Response(200, json={"results": [{"response": {"doi": "10.1/x", "title": "Wrapped"}}]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = UnpaywallClient(client=http, email="dev@example.com")
            return await client.search("wrapped")

    results = asyncio.run(run())

    assert results[0].source_title == "Wrapped"
