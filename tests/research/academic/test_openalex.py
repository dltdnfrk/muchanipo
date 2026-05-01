import asyncio

import httpx

from src.research.academic import openalex
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
                        "doi": "https://doi.org/10.1234/example",
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
    assert results[0].provenance["doi"] == "10.1234/example"
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


def test_openalex_targeting_queries_map_entities_without_async_loop(monkeypatch):
    requests = []

    class FakeResponse:
        def __init__(self, endpoint):
            self.endpoint = endpoint

        def json(self):
            if self.endpoint == "/works":
                return {
                    "results": [
                        {"display_name": "A paper", "doi": "https://doi.org/10.1234/example"},
                    ]
                }
            return {
                "results": [
                    {"display_name": "Seoul National University", "doi": None},
                    {"display_name": "Precision Agriculture", "doi": "https://doi.org/10.1234/example"},
                ]
            }

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, endpoint, params):
            requests.append((endpoint, dict(params)))
            return FakeResponse(endpoint)

    monkeypatch.setattr(openalex, "_skip_live_targeting", lambda: False)
    monkeypatch.setattr(openalex.httpx, "Client", FakeClient)

    institutions, inst_prov = openalex.query_institutions(["agriculture"], limit=1)
    journals, journal_prov = openalex.query_journals(["agriculture"], limit=1)
    papers, paper_prov = openalex.query_seed_papers(["agriculture"], limit=1)

    assert institutions == ["Seoul National University"]
    assert journals == ["Seoul National University"]
    assert papers == ["10.1234/example"]
    assert requests[0][0] == "/institutions"
    assert requests[1][0] == "/sources"
    assert requests[1][1]["filter"] == "type:journal"
    assert requests[2][0] == "/works"
    assert inst_prov[0]["status"] == journal_prov[0]["status"] == paper_prov[0]["status"] == "ok"
