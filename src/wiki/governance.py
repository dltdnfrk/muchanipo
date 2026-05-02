"""Raw-to-wiki governance records for Karpathy-style LLM wiki flows."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any


def build_dual_path_governance(
    *,
    artifact_id: str,
    raw_source: dict[str, Any],
    wiki_markdown: str,
) -> dict[str, Any]:
    """Record the raw/source path and compiled wiki path as separate artifacts."""
    safe_id = _safe_id(artifact_id)
    raw_json = json.dumps(raw_source, ensure_ascii=False, sort_keys=True, default=str)
    wiki_text = str(wiki_markdown or "")
    raw_hash = _sha256(raw_json)
    wiki_hash = _sha256(wiki_text)
    headings = _markdown_headings(wiki_text)
    source_ids = _source_ids(raw_source)
    outbound_links = _markdown_links(wiki_text)
    return {
        "pattern": "Karpathy LLM Wiki Pattern",
        "artifact_id": safe_id,
        "raw_path": f"raw/{safe_id}.json",
        "wiki_path": f"wiki/{safe_id}.md",
        "index_path": f"index/{safe_id}.json",
        "manifest_path": "wiki/manifest.json",
        "raw_sha256": raw_hash,
        "wiki_sha256": wiki_hash,
        "separate_paths": True,
        "hashes_differ": raw_hash != wiki_hash,
        "raw_format": "json",
        "wiki_format": "markdown",
        "wiki_title": headings[0] if headings else safe_id,
        "heading_count": len(headings),
        "headings": headings,
        "outbound_links": outbound_links,
        "source_ids": source_ids,
        "source_count": len(source_ids),
        "entries": [
            {
                "kind": "raw_source",
                "path": f"raw/{safe_id}.json",
                "sha256": raw_hash,
                "bytes": len(raw_json.encode("utf-8")),
            },
            {
                "kind": "compiled_wiki",
                "path": f"wiki/{safe_id}.md",
                "sha256": wiki_hash,
                "bytes": len(wiki_text.encode("utf-8")),
            },
            {
                "kind": "search_index",
                "path": f"index/{safe_id}.json",
                "sha256": _sha256(json.dumps({"headings": headings, "source_ids": source_ids}, sort_keys=True)),
            },
        ],
        "maintenance_policy": {
            "raw_is_source_of_truth": True,
            "compiled_markdown_is_derivative": True,
            "rebuild_when_raw_hash_changes": True,
            "preserve_raw_before_updating_wiki": True,
        },
    }


def validate_dual_path_governance(record: dict[str, Any]) -> bool:
    return (
        record.get("separate_paths") is True
        and str(record.get("raw_path") or "").startswith("raw/")
        and str(record.get("wiki_path") or "").startswith("wiki/")
        and bool(record.get("raw_sha256"))
        and bool(record.get("wiki_sha256"))
        and record.get("raw_path") != record.get("wiki_path")
        and str(record.get("index_path") or "").startswith("index/")
        and isinstance(record.get("entries"), list)
        and bool(record.get("maintenance_policy", {}).get("raw_is_source_of_truth"))
    )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip(".-")
    return safe or "artifact"


def _markdown_headings(markdown: str) -> list[str]:
    headings: list[str] = []
    for line in str(markdown or "").splitlines():
        match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
        if match:
            headings.append(match.group(1).strip())
    return headings


def _markdown_links(markdown: str) -> list[str]:
    links: list[str] = []
    for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", str(markdown or "")):
        link = match.group(1).strip()
        if link and link not in links:
            links.append(link)
    for match in re.finditer(r"\[\[([^\]]+)\]\]", str(markdown or "")):
        link = match.group(1).strip()
        if link and link not in links:
            links.append(link)
    return links


def _source_ids(value: Any) -> list[str]:
    ids: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key in ("id", "source_id", "source_url", "doi"):
                raw = item.get(key)
                if raw:
                    text = str(raw).strip()
                    if text and text not in ids:
                        ids.append(text)
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return ids
