import asyncio

import httpx

from src.evidence.artifact import EvidenceRef
from src.research.academic import (
    ArxivClient,
    CoreClient,
    CrossRefClient,
    OpenAlexClient,
    SemanticScholarClient,
    UnpaywallClient,
)


ARXIV_ATOM = """<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2501.00001v1</id>
    <title>Agent Memory</title>
    <summary>Memory systems for agents.</summary>
    <published>2025-01-01T00:00:00Z</published>
  </entry>
</feed>"""


def test_all_academic_clients_share_evidence_interface():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/works" and request.url.host == "api.openalex.org":
            return httpx.Response(200, json={"results": [{"id": "https://openalex.org/W1", "display_name": "OpenAlex"}]})
        if path == "/graph/v1/paper/search":
            return httpx.Response(200, json={"data": [{"paperId": "S2", "title": "Semantic Scholar"}]})
        if path == "/v3/search/works":
            return httpx.Response(200, json={"results": [{"id": 1, "title": "CORE"}]})
        if path == "/works" and request.url.host == "api.crossref.org":
            return httpx.Response(200, json={"message": {"items": [{"DOI": "10.1/cross", "title": ["CrossRef"]}]}})
        if path == "/api/query":
            return httpx.Response(200, text=ARXIV_ATOM)
        if path == "/v2/search":
            return httpx.Response(200, json={"results": [{"response": {"doi": "10.1/oa", "title": "Unpaywall"}}]})
        raise AssertionError(f"unexpected request: {request.url}")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            clients = [
                OpenAlexClient(client=http, email="dev@example.com"),
                SemanticScholarClient(client=http, min_interval_seconds=0),
                CoreClient(client=http, min_interval_seconds=0),
                CrossRefClient(client=http, email="dev@example.com"),
                ArxivClient(client=http, min_interval_seconds=0),
                UnpaywallClient(client=http, email="dev@example.com"),
            ]
            return [await client.search("agent memory", limit=1) for client in clients]

    batches = asyncio.run(run())
    evidence = [batch[0] for batch in batches]

    assert len(evidence) == 6
    assert all(isinstance(item, EvidenceRef) for item in evidence)
    assert {item.provenance["kind"] for item in evidence} == {
        "openalex",
        "semantic_scholar",
        "core",
        "crossref",
        "arxiv",
        "unpaywall",
    }
    assert all(item.provenance["source_text"] for item in evidence)
