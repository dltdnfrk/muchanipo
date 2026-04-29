"""Synchronous adapter for the async academic search clients."""
from __future__ import annotations

import asyncio
import threading
from typing import Awaitable, Callable, List

from src.evidence.artifact import EvidenceRef

from .arxiv import search as arxiv_search
from .core import search as core_search
from .crossref import search as crossref_search
from .openalex import search as openalex_search
from .semantic_scholar import search as semantic_scholar_search
from .unpaywall import search as unpaywall_search


DEFAULT_LIMIT = 2
AsyncSearchFn = Callable[[str, int], Awaitable[List[EvidenceRef]]]
DEFAULT_SEARCH_FNS = (
    openalex_search,
    semantic_scholar_search,
    crossref_search,
    core_search,
    arxiv_search,
    unpaywall_search,
)


async def _search_one(search_fn: AsyncSearchFn, query: str, limit: int) -> list[EvidenceRef]:
    try:
        return await search_fn(query, limit=limit)
    except Exception:  # noqa: BLE001 - one academic backend should not fail the whole search
        return []


async def _search_all(query: str, limit: int) -> list[EvidenceRef]:
    batches = await asyncio.gather(*(_search_one(search_fn, query, limit) for search_fn in DEFAULT_SEARCH_FNS))
    evidence: list[EvidenceRef] = []
    for batch in batches:
        evidence.extend(batch)
    return evidence


def _run_sync(coro: Awaitable[list[EvidenceRef]]) -> list[EvidenceRef]:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: list[EvidenceRef] = []
    error: BaseException | None = None

    def _runner() -> None:
        nonlocal result, error
        try:
            result = asyncio.run(coro)
        except BaseException as exc:  # pragma: no cover - defensive thread handoff
            error = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if error is not None:
        raise error
    return result


def search(query: str, limit: int = DEFAULT_LIMIT) -> list[EvidenceRef]:
    """Synchronously aggregate academic evidence across the existing async clients."""
    try:
        return _run_sync(_search_all(query, limit))
    except Exception:  # noqa: BLE001 - default live wiring must degrade gracefully
        return []
