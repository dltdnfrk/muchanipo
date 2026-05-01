import asyncio

import httpx

from src.research.academic.core import CoreClient


def test_core_search_maps_full_text_result():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v3/search/works"
        assert request.headers["authorization"] == "Bearer core-key"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": 42,
                        "title": "Full text paper",
                        "abstract": "A useful abstract",
                        "fullText": "Full text body",
                        "doi": "10.777/core",
                        "downloadUrl": "https://core.ac.uk/download/42",
                    }
                ]
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = CoreClient(client=http, api_key="core-key", min_interval_seconds=0)
            return await client.search("full text")

    results = asyncio.run(run())

    assert results[0].id == "core:42"
    assert results[0].source_url == "https://core.ac.uk/download/42"
    assert results[0].quote == "A useful abstract Full text body"
    assert results[0].provenance["doi"] == "10.777/core"
    assert results[0].provenance["source_text"]["fullText"] == "Full text body"


def test_core_get_citations_is_explicitly_unsupported():
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(500))) as http:
            client = CoreClient(client=http, min_interval_seconds=0)
            return await client.get_citations("42")

    assert asyncio.run(run()) == []
