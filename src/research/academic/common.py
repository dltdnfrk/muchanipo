"""Shared primitives for academic API clients."""
from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Mapping
from typing import Any

import httpx

from src.evidence.artifact import EvidenceRef
from src.evidence.provenance import Provenance


DEFAULT_CONTACT_EMAIL = "research@muchanipo.local"
DEFAULT_TIMEOUT = 10.0
MAX_RETRIES = 3


def contact_email() -> str:
    return (
        os.getenv("MUCHANIPO_CONTACT_EMAIL")
        or os.getenv("UNPAYWALL_EMAIL")
        or DEFAULT_CONTACT_EMAIL
    )


def compact_text(parts: list[Any]) -> str | None:
    text = " ".join(str(part).strip() for part in parts if part)
    return text or None


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    doi = value.strip()
    prefixes = ("https://doi.org/", "http://doi.org/", "doi:")
    lowered = doi.lower()
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return doi[len(prefix) :]
    return doi


def source_grade_for_paper(doi: str | None = None, peer_reviewed: bool = True) -> str:
    if doi and peer_reviewed:
        return "A"
    return "B"


def evidence_ref(
    *,
    source: str,
    paper_id: str,
    raw: Mapping[str, Any],
    source_url: str | None,
    source_title: str | None,
    quote: str | None,
    source_grade: str = "A",
) -> EvidenceRef:
    return EvidenceRef(
        id=f"{source}:{paper_id}",
        source_url=source_url,
        source_title=source_title,
        quote=quote,
        source_grade=source_grade,
        provenance=Provenance(
            kind=source,
            metadata={
                "paper_id": paper_id,
                "source_text": dict(raw),
            },
        ).as_dict(),
    )


class AcademicHttpClient:
    """Tiny async HTTP wrapper with semaphore rate gates and retry policy."""

    def __init__(
        self,
        *,
        base_url: str,
        headers: Mapping[str, str] | None = None,
        max_concurrency: int = 1,
        min_interval_seconds: float = 0.0,
        client: httpx.AsyncClient | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = dict(headers or {})
        self._client = client
        self._owns_client = client is None
        self._timeout = timeout
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))
        self._min_interval_seconds = max(0.0, min_interval_seconds)
        self._last_request_at = 0.0
        self._interval_lock = asyncio.Lock()

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def __aenter__(self) -> "AcademicHttpClient":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def get_json(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        response = await self.get(path, params=params, headers=headers)
        return response.json()

    async def get(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        request_headers = {**self.headers, **dict(headers or {})}
        async with self._semaphore:
            await self._respect_interval()
            for attempt in range(MAX_RETRIES):
                try:
                    response = await self._ensure_client().get(
                        self._url(path),
                        params=dict(params or {}),
                        headers=request_headers,
                        timeout=self._timeout,
                    )
                    if response.status_code >= 500:
                        raise httpx.HTTPStatusError(
                            f"server error {response.status_code}",
                            request=response.request,
                            response=response,
                        )
                    response.raise_for_status()
                    return response
                except (httpx.TimeoutException, httpx.HTTPStatusError):
                    if attempt == MAX_RETRIES - 1:
                        raise
                    await asyncio.sleep(0.25 * (2**attempt))
        raise RuntimeError("unreachable retry state")

    async def _respect_interval(self) -> None:
        if self._min_interval_seconds <= 0:
            return
        async with self._interval_lock:
            elapsed = time.monotonic() - self._last_request_at
            wait_for = self._min_interval_seconds - elapsed
            if wait_for > 0:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, time.sleep, wait_for)
            self._last_request_at = time.monotonic()

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url)
        return self._client

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.base_url}/{path.lstrip('/')}"
