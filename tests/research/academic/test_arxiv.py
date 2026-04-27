import asyncio

import httpx

from src.research.academic.arxiv import ArxivClient


ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2501.00001v1</id>
    <title>Agent Memory</title>
    <summary>Memory systems for agents.</summary>
    <published>2025-01-01T00:00:00Z</published>
    <updated>2025-01-02T00:00:00Z</updated>
    <author><name>Ada Lovelace</name></author>
  </entry>
</feed>
"""


def test_arxiv_search_parses_atom_entries_and_preserves_xml():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/query"
        assert request.url.params["search_query"] == "agent memory"
        return httpx.Response(200, text=ATOM)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = ArxivClient(client=http, min_interval_seconds=0)
            return await client.search("agent memory")

    results = asyncio.run(run())

    assert results[0].id == "arxiv:http://arxiv.org/abs/2501.00001v1"
    assert results[0].source_grade == "B"
    assert results[0].quote == "Memory systems for agents. 2025-01-01T00:00:00Z"
    assert "Agent Memory" in results[0].provenance["source_text"]["raw_entry_xml"]


def test_arxiv_get_paper_uses_id_list():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["id_list"] == "2501.00001v1"
        return httpx.Response(200, text=ATOM)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = ArxivClient(client=http, min_interval_seconds=0)
            return await client.get_paper("http://arxiv.org/abs/2501.00001v1")

    result = asyncio.run(run())

    assert result is not None
    assert result.source_title == "Agent Memory"
