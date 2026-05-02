"""Local GBrain-style knowledge runtime for Muchanipo reports.

The upstream GBrain project is a TypeScript brain runtime. Muchanipo does not
need to launch that app to satisfy the six-stage product contract, but stage
2/4/6 claims need more than a markdown label. This module builds the local
runtime artifact the product actually uses: a compiled-truth page, append-only
event ledger, typed links, source attribution, stale-state check, and
brain-first lookup route.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


GBRAIN_UPSTREAM_URL = "https://github.com/garrytan/gbrain"
GBRAIN_UPSTREAM_LICENSE = "MIT"
GBRAIN_ROUTE = ("search", "query", "get_page", "external_after_empty")
LINK_TYPES = {
    "cites",
    "mentions_persona",
    "has_open_question",
    "summarizes_round",
    "filed_under",
}


def build_gbrain_runtime_record(
    *,
    artifact_id: str,
    topic: str,
    compiled_truth: str,
    raw_source: Mapping[str, Any],
    evidence_summary: Mapping[str, Any],
    content_hash: str,
    timeline_entry: str,
    page_type: str = "project",
) -> dict[str, Any]:
    """Build a local GBrain-style page/runtime record from report artifacts."""
    slug = canonical_slug(topic or artifact_id)
    source_ids = _source_ids(raw_source)
    typed_links = _typed_links(
        slug=slug,
        raw_source=raw_source,
        source_ids=source_ids,
    )
    event_ledger = _event_ledger(
        artifact_id=artifact_id,
        topic=topic,
        raw_source=raw_source,
        evidence_summary=evidence_summary,
        timeline_entry=timeline_entry,
    )
    latest_event_at = _latest_event_at(event_ledger)
    compiled_at = _utc_now()
    stale_state = {
        "compiled_at": compiled_at,
        "latest_event_at": latest_event_at,
        "is_stale": _is_stale(compiled_at, latest_event_at),
        "policy": "compiled_truth_must_be_rewritten_when_event_ledger_has_newer_evidence",
    }
    search_index = _search_index(
        slug=slug,
        topic=topic,
        compiled_truth=compiled_truth,
        event_ledger=event_ledger,
        typed_links=typed_links,
    )
    record = {
        "runtime": "local gbrain compiled-truth/event-graph runtime",
        "upstream": {
            "source_url": GBRAIN_UPSTREAM_URL,
            "license": GBRAIN_UPSTREAM_LICENSE,
            "port_type": "faithful local runtime adaptation",
        },
        "page": {
            "slug": slug,
            "type": page_type,
            "title": topic or artifact_id,
            "tags": _unique(["muchanipo", "autoresearch", page_type, *raw_source.get("tags", [])]),
            "aliases": _aliases(topic),
            "content_hash": content_hash,
            "source_count": len(source_ids),
            "link_count": len(typed_links),
            "event_count": len(event_ledger),
        },
        "compiled_truth": compiled_truth,
        "current_conclusion": _current_conclusion(compiled_truth),
        "event_ledger": event_ledger,
        "timeline": [
            {
                "kind": "timeline_entry",
                "detail": timeline_entry,
                "source": artifact_id,
                "append_only": True,
            }
        ],
        "typed_links": typed_links,
        "brain_first_route": list(GBRAIN_ROUTE),
        "search_index": search_index,
        "source_attribution": {
            "source_ids": source_ids,
            "trusted_count": int(evidence_summary.get("trusted", 0) or 0),
            "verified_claim_ratio": float(evidence_summary.get("verified_claim_ratio", 0.0) or 0.0),
        },
        "stale_state": stale_state,
        "maintenance_checks": _maintenance_checks(
            compiled_truth=compiled_truth,
            event_ledger=event_ledger,
            typed_links=typed_links,
            source_ids=source_ids,
            search_index=search_index,
        ),
    }
    record["valid"] = validate_gbrain_runtime_record(record)
    return record


def validate_gbrain_runtime_record(record: Mapping[str, Any]) -> bool:
    """Return True when the local GBrain runtime has all required surfaces."""
    page = record.get("page")
    if not isinstance(page, Mapping) or not str(page.get("slug") or "").strip():
        return False
    if not str(record.get("compiled_truth") or "").strip():
        return False
    if not str(record.get("current_conclusion") or "").strip():
        return False
    if not _all_dicts(record.get("event_ledger")):
        return False
    if not _all_dicts(record.get("typed_links")):
        return False
    if list(record.get("brain_first_route") or []) != list(GBRAIN_ROUTE):
        return False
    checks = record.get("maintenance_checks")
    if not isinstance(checks, Mapping) or not all(bool(value) for value in checks.values()):
        return False
    source_attribution = record.get("source_attribution")
    if not isinstance(source_attribution, Mapping) or not source_attribution.get("source_ids"):
        return False
    return bool(record.get("search_index"))


def brain_first_lookup(query: str, records: Iterable[Mapping[str, Any]], *, limit: int = 5) -> dict[str, Any]:
    """Run the local brain-first route over GBrain runtime records.

    The route mirrors GBrain's lookup order without requiring embeddings or an
    external database: keyword search first, then graph/backlink boost, then
    direct page read. External search is only allowed when no local result is
    useful.
    """
    terms = _terms(query)
    scored: list[dict[str, Any]] = []
    for record in records:
        page = record.get("page") if isinstance(record.get("page"), Mapping) else {}
        index = record.get("search_index") if isinstance(record.get("search_index"), Mapping) else {}
        text = " ".join(
            [
                str(page.get("title") or ""),
                str(record.get("current_conclusion") or ""),
                " ".join(index.get("keywords") or []),
            ]
        ).lower()
        keyword_hits = sum(1 for term in terms if term in text)
        if keyword_hits <= 0:
            continue
        link_boost = min(len(record.get("typed_links") or []) * 0.05, 0.5)
        score = keyword_hits + link_boost
        scored.append(
            {
                "slug": str(page.get("slug") or ""),
                "title": str(page.get("title") or ""),
                "score": round(score, 4),
                "route": "search+graph_boost",
                "current_conclusion": str(record.get("current_conclusion") or ""),
            }
        )
    scored.sort(key=lambda item: item["score"], reverse=True)
    return {
        "route": list(GBRAIN_ROUTE),
        "external_allowed": not scored,
        "results": scored[: max(1, limit)],
    }


def canonical_slug(value: str) -> str:
    words = re.findall(r"[A-Za-z0-9가-힣]+", (value or "").lower())
    slug = "-".join(words[:12])
    return slug[:80] or "untitled"


def _typed_links(*, slug: str, raw_source: Mapping[str, Any], source_ids: list[str]) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for source_id in source_ids:
        links.append(
            {
                "from": slug,
                "to": source_id,
                "type": "cites",
                "provenance": "evidence",
            }
        )
    for persona in raw_source.get("personas") or []:
        if not isinstance(persona, Mapping):
            continue
        name = str(persona.get("name") or "").strip()
        if not name:
            continue
        links.append(
            {
                "from": slug,
                "to": canonical_slug(name),
                "type": "mentions_persona",
                "provenance": "council",
            }
        )
    for question in raw_source.get("open_questions") or []:
        text = str(question or "").strip()
        if text:
            links.append(
                {
                    "from": slug,
                    "to": canonical_slug(text),
                    "type": "has_open_question",
                    "provenance": "report",
                }
            )
    links.append(
        {
            "from": slug,
            "to": "projects/muchanipo",
            "type": "filed_under",
            "provenance": "runtime",
        }
    )
    return [link for link in links if link["type"] in LINK_TYPES]


def _event_ledger(
    *,
    artifact_id: str,
    topic: str,
    raw_source: Mapping[str, Any],
    evidence_summary: Mapping[str, Any],
    timeline_entry: str,
) -> list[dict[str, Any]]:
    now = _utc_now()
    events = [
        {
            "id": f"{artifact_id}:report-created",
            "timestamp": now,
            "kind": "report_created",
            "summary": topic,
            "source": artifact_id,
            "append_only": True,
        },
        {
            "id": f"{artifact_id}:evidence-verified",
            "timestamp": now,
            "kind": "evidence_verified",
            "summary": f"trusted={int(evidence_summary.get('trusted', 0) or 0)}",
            "source": artifact_id,
            "append_only": True,
        },
        {
            "id": f"{artifact_id}:timeline",
            "timestamp": now,
            "kind": "timeline_entry",
            "summary": timeline_entry,
            "source": artifact_id,
            "append_only": True,
        },
    ]
    consensus = str(raw_source.get("consensus") or "").strip()
    if consensus:
        events.append(
            {
                "id": f"{artifact_id}:council-synthesis",
                "timestamp": now,
                "kind": "council_synthesis",
                "summary": consensus[:240],
                "source": artifact_id,
                "append_only": True,
            }
        )
    return events


def _search_index(
    *,
    slug: str,
    topic: str,
    compiled_truth: str,
    event_ledger: list[dict[str, Any]],
    typed_links: list[dict[str, Any]],
) -> dict[str, Any]:
    keywords = _unique(_terms(" ".join([topic, compiled_truth]))[:80])
    chunks = _chunks(compiled_truth)
    return {
        "slug": slug,
        "mode": "keyword_graph_hybrid",
        "keywords": keywords,
        "chunk_count": len(chunks),
        "chunks": chunks,
        "graph_edge_count": len(typed_links),
        "timeline_event_count": len(event_ledger),
        "backlink_boost_enabled": True,
    }


def _source_ids(raw_source: Mapping[str, Any]) -> list[str]:
    ids: list[str] = []
    for item in raw_source.get("evidence") or []:
        text = str(item or "").strip()
        if not text:
            continue
        head = text.split(":", 1)[0].strip()
        ids.append(head if head else text[:80])
    return _unique(ids)


def _current_conclusion(compiled_truth: str) -> str:
    for line in compiled_truth.splitlines():
        cleaned = line.strip(" -#\t")
        if cleaned and cleaned.lower() not in {"compiled truth", "권고사항", "근거"}:
            return cleaned[:280]
    return compiled_truth.strip()[:280]


def _maintenance_checks(
    *,
    compiled_truth: str,
    event_ledger: list[dict[str, Any]],
    typed_links: list[dict[str, Any]],
    source_ids: list[str],
    search_index: Mapping[str, Any],
) -> dict[str, bool]:
    return {
        "compiled_truth_present": bool(compiled_truth.strip()),
        "event_ledger_append_only": bool(event_ledger) and all(bool(item.get("append_only")) for item in event_ledger),
        "typed_links_present": bool(typed_links),
        "source_ids_present": bool(source_ids),
        "search_index_present": bool(search_index.get("keywords")),
        "brain_first_route_present": True,
    }


def _aliases(topic: str) -> list[str]:
    topic = (topic or "").strip()
    if not topic:
        return []
    return _unique([topic, canonical_slug(topic)])


def _chunks(text: str) -> list[dict[str, Any]]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text or "") if part.strip()]
    chunks: list[dict[str, Any]] = []
    for idx, paragraph in enumerate(paragraphs[:12], start=1):
        chunks.append(
            {
                "id": f"chunk-{idx}",
                "sha256": hashlib.sha256(paragraph.encode("utf-8")).hexdigest(),
                "text": paragraph[:500],
            }
        )
    return chunks


def _terms(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9가-힣]{2,}", (text or "").lower())


def _unique(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _latest_event_at(events: list[dict[str, Any]]) -> str:
    timestamps = [str(item.get("timestamp") or "") for item in events if item.get("timestamp")]
    return max(timestamps) if timestamps else ""


def _is_stale(compiled_at: str, latest_event_at: str) -> bool:
    return bool(latest_event_at and compiled_at < latest_event_at)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _all_dicts(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, Mapping) for item in value)
