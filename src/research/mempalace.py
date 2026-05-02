"""Local MemPalace-style markdown memory index.

The upstream MemPalace dependency is not vendored. This module provides the
runtime behavior Muchanipo needs from the reference: search local knowledge by
wing, room, and source-backed snippets before falling back to web results.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class MemoryRecord:
    text: str
    source: str
    score: float
    wing: str
    room: str
    path: str

    def as_dict(self) -> dict[str, str | float]:
        return {
            "text": self.text,
            "source": self.source,
            "score": self.score,
            "wing": self.wing,
            "room": self.room,
            "path": self.path,
        }


def search_memory_palace(
    query: str,
    *,
    wing: str | None = None,
    room: str | None = None,
    limit: int = 5,
    roots: Iterable[Path | str] | None = None,
) -> list[dict[str, str | float]]:
    """Search markdown memory roots with MemPalace wing/room metadata."""
    cleaned_query = " ".join(str(query or "").split())
    if not cleaned_query:
        return []
    terms = _terms(cleaned_query)
    if not terms:
        return []

    records: list[MemoryRecord] = []
    for root in _memory_roots(roots):
        if not root.exists() or not root.is_dir():
            continue
        for path in _iter_markdown(root):
            records.extend(
                _records_for_path(
                    root=root,
                    path=path,
                    terms=terms,
                    wing_filter=wing,
                    room_filter=room,
                )
            )
    records.sort(key=lambda item: (item.score, item.source), reverse=True)
    return [record.as_dict() for record in records[: max(0, int(limit))]]


def remember_memory(
    *,
    title: str,
    text: str,
    wing: str = "inbox",
    room: str = "notes",
    metadata: dict[str, Any] | None = None,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Persist a source-backed memory note into a MemPalace wing/room."""
    cleaned_title = _clean_title(title) or "memory"
    cleaned_text = str(text or "").strip()
    if not cleaned_text:
        raise ValueError("memory text must not be empty")
    root_path = Path(root).expanduser() if root is not None else _memory_roots(None)[0]
    wing_slug = _slug(wing) or "inbox"
    room_slug = _slug(room) or "notes"
    target_dir = root_path / wing_slug / room_slug
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{_slug(cleaned_title)}.md"
    payload = {
        "title": cleaned_title,
        "wing": wing_slug,
        "room": room_slug,
        "metadata": dict(metadata or {}),
    }
    body = "\n".join(
        [
            "<!-- muchanipo-mempalace",
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            "-->",
            "",
            f"# {cleaned_title}",
            "",
            cleaned_text,
            "",
        ]
    )
    path.write_text(body, encoding="utf-8")
    relative = _relative_path(path, root_path).as_posix()
    return {
        "path": relative,
        "source": f"mempalace:{relative}#{_slug(cleaned_title)}",
        "wing": wing_slug,
        "room": room_slug,
        "sha256": _sha256(body),
        "bytes": len(body.encode("utf-8")),
    }


def build_memory_manifest(*, root: Path | str) -> dict[str, Any]:
    """Build a search/runtime manifest for stored MemPalace notes."""
    root_path = Path(root).expanduser()
    records: list[dict[str, Any]] = []
    for path in _iter_markdown(root_path):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        relative = _relative_path(path, root_path)
        headings = [room for room, _text in _rooms(text)]
        wing = relative.parts[0] if len(relative.parts) > 1 else "root"
        room = relative.parts[1] if len(relative.parts) > 2 else (headings[0] if headings else "root")
        records.append(
            {
                "path": relative.as_posix(),
                "wing": wing,
                "room": room,
                "sha256": _sha256(text),
                "headings": headings,
                "bytes": len(text.encode("utf-8")),
            }
        )
    records.sort(key=lambda item: str(item["path"]))
    return {
        "pattern": "MemPalace local memory runtime",
        "root": str(root_path),
        "record_count": len(records),
        "wings": sorted({str(item["wing"]) for item in records}),
        "rooms": sorted({str(item["room"]) for item in records}),
        "records": records,
    }


def _memory_roots(roots: Iterable[Path | str] | None) -> list[Path]:
    if roots is not None:
        return _dedupe_paths(Path(item).expanduser() for item in roots)

    candidates: list[Path] = []
    for env_name in ("MUCHANIPO_MEMPALACE_ROOT", "MUCHANIPO_VAULT_PATH", "MUCHANIPO_VAULT_ROOT"):
        raw = os.environ.get(env_name)
        if raw:
            candidates.append(Path(raw).expanduser())

    project_vault = Path(__file__).resolve().parents[2] / "vault"
    candidates.append(project_vault)

    obsidian = Path("~/Documents/Hyunjun").expanduser()
    candidates.append(obsidian)
    return _dedupe_paths(candidates)


def _dedupe_paths(paths: Iterable[Path]) -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []
    for path in paths:
        resolved = path.resolve() if path.exists() else path
        if resolved in seen:
            continue
        seen.add(resolved)
        out.append(path)
    return out


def _iter_markdown(root: Path) -> Iterable[Path]:
    try:
        yield from root.rglob("*.md")
    except OSError:
        return


def _records_for_path(
    *,
    root: Path,
    path: Path,
    terms: set[str],
    wing_filter: str | None,
    room_filter: str | None,
) -> list[MemoryRecord]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    relative = _relative_path(path, root)
    wing = relative.parts[0] if len(relative.parts) > 1 else "root"
    if wing_filter and wing_filter.lower() not in wing.lower():
        return []
    path_room = relative.parts[1] if len(relative.parts) > 2 else ""

    records: list[MemoryRecord] = []
    for room_name, room_text in _rooms(text):
        if room_filter and (
            room_filter.lower() not in room_name.lower()
            and room_filter.lower() not in path_room.lower()
        ):
            continue
        score = _score(room_text, terms)
        if score <= 0:
            continue
        snippet = _snippet(room_text, terms)
        records.append(
            MemoryRecord(
                text=snippet,
                source=f"mempalace:{relative.as_posix()}#{_slug(room_name)}",
                score=score,
                wing=wing,
                room=room_name,
                path=relative.as_posix(),
            )
        )
    return records


def _relative_path(path: Path, root: Path) -> Path:
    try:
        return path.relative_to(root)
    except ValueError:
        return path


def _rooms(text: str) -> Iterable[tuple[str, str]]:
    current = "root"
    buffer: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            if buffer:
                yield current, "\n".join(buffer)
            current = match.group(2).strip()
            buffer = [line]
            continue
        buffer.append(line)
    if buffer:
        yield current, "\n".join(buffer)


def _terms(query: str) -> set[str]:
    return {
        term.lower()
        for term in re.findall(r"[\w가-힣]+", query)
        if len(term) >= 2
    }


def _score(text: str, terms: set[str]) -> float:
    lowered = text.lower()
    matched = sum(1 for term in terms if term in lowered)
    if matched == 0:
        return 0.0
    frequency = sum(lowered.count(term) for term in terms)
    coverage = matched / max(1, len(terms))
    return round(min(1.0, coverage * 0.8 + min(frequency, 5) * 0.04), 4)


def _snippet(text: str, terms: set[str], *, window: int = 180) -> str:
    compact = " ".join(text.split())
    lowered = compact.lower()
    positions = [lowered.find(term) for term in terms if lowered.find(term) >= 0]
    if not positions:
        return compact[:window]
    center = min(positions)
    start = max(0, center - window // 2)
    end = min(len(compact), center + window // 2)
    return compact[start:end].strip()


def _slug(value: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z가-힣]+", "-", value.strip()).strip("-")
    return slug or "root"


def _clean_title(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
