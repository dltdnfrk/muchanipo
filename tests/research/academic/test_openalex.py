import asyncio

import httpx

from src.research.academic.openalex import OpenAlexClient


def test_openalex_search_maps_results_to_evidence():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/works"
        assert request.url.params["mailto"] == "dev@example.com"
        assert request.headers["from"] == "dev@example.com"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "https://openalex.org/W1",
                        "doi": "https://doi.org/10.123/example",
                        "display_name": "A paper",
                        "publication_year": 2024,
                        "abstract_inverted_index": {"hello": [0], "world": [1]},
                    }
                ]
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = OpenAlexClient(client=http, email="dev@example.com")
            return await client.search("agent memory")

    results = asyncio.run(run())

    assert len(results) == 1
    assert results[0].id == "openalex:https://openalex.org/W1"
    assert results[0].source_grade == "A"
    assert results[0].quote == "hello world 2024"
    assert results[0].provenance["source_text"]["display_name"] == "A paper"


def test_openalex_get_citations_uses_cites_filter():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["filter"] == "cites:W1"
        return httpx.Response(200, json={"results": [{"id": "https://openalex.org/W2", "display_name": "Citing"}]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = OpenAlexClient(client=http, email="dev@example.com")
            return await client.get_citations("https://openalex.org/W1", limit=5)

    results = asyncio.run(run())

    assert results[0].source_title == "Citing"
