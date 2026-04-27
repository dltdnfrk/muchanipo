import asyncio

import httpx

from src.research.academic.crossref import CrossRefClient


def test_crossref_search_maps_message_items():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/works"
        assert request.url.params["mailto"] == "dev@example.com"
        assert request.headers["from"] == "dev@example.com"
        return httpx.Response(
            200,
            json={
                "message": {
                    "items": [
                        {
                            "DOI": "10.1000/cross",
                            "title": ["CrossRef Paper"],
                            "container-title": ["Journal"],
                            "URL": "https://doi.org/10.1000/cross",
                        }
                    ]
                }
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = CrossRefClient(client=http, email="dev@example.com")
            return await client.search("metadata")

    results = asyncio.run(run())

    assert results[0].id == "crossref:10.1000/cross"
    assert results[0].source_title == "CrossRef Paper"
    assert results[0].quote == "Journal"
    assert results[0].provenance["source_text"]["DOI"] == "10.1000/cross"


def test_crossref_get_paper_normalizes_doi():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/works/10.1000/cross"
        return httpx.Response(200, json={"message": {"DOI": "10.1000/cross", "title": ["Paper"]}})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = CrossRefClient(client=http, email="dev@example.com")
            return await client.get_paper("https://doi.org/10.1000/cross")

    result = asyncio.run(run())

    assert result is not None
    assert result.id == "crossref:10.1000/cross"
