#!/usr/bin/env python3
"""Episodic-to-semantic promotion loop for wiki memory.

DreamCycle keeps short episodic observations until the same theme repeats
enough times, then writes a compiled-truth page through the lockdown write
guard.  The implementation is intentionally dependency-free so it can run from
nightly automation.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, DefaultDict, Dict, Iterable, List, Mapping

try:
    from src.safety.lockdown import guard_write
except Exception:  # pragma: no cover - standalone fallback
    def guard_write(path: str | Path) -> tuple[bool, str]:
        return True, "allowed"


@dataclass(frozen=True)
class Episode:
    """A single observed memory event."""

    key: str
    content: str
    source: str = "runtime"
    weight: int = 1


@dataclass
class DreamCycle:
    """Accumulate repeated episodes and promote stable truths.

    한국어 주석: 반복적으로 관찰된 에피소드만 semantic truth 후보로 승격한다.
    """

    threshold: int = 3
    _episodes: List[Episode] = field(default_factory=list)
    _counts: Counter[str] = field(default_factory=Counter)
    _contents: DefaultDict[str, List[str]] = field(default_factory=lambda: defaultdict(list))

    def __post_init__(self) -> None:
        if self.threshold < 1:
            raise ValueError("threshold must be >= 1")

    def accumulate(self, episode: Episode | Mapping[str, Any] | str) -> Episode:
        """Store an episode and return its normalized representation."""
        normalized = self._normalize_episode(episode)
        self._episodes.append(normalized)
        self._counts[normalized.key] += max(1, normalized.weight)
        self._contents[normalized.key].append(normalized.content)
        return normalized

    def should_promote(self) -> bool:
        """Return True when any episode key has met the repetition threshold."""
        return any(count >= self.threshold for count in self._counts.values())

    def promotion_candidates(self) -> Dict[str, int]:
        """Return keys whose observed count is ready for compiled-truth promotion."""
        return {
            key: count
            for key, count in self._counts.items()
            if count >= self.threshold
        }

    def compile_truth(self, key: str) -> str:
        """Build a compact compiled-truth body from observations for one key."""
        if key not in self._contents:
            raise KeyError(f"unknown episode key: {key}")

        observations = self._contents[key]
        unique_observations = list(dict.fromkeys(observations))
        lines = [
            f"# {key}",
            "",
            f"- observations: {len(observations)}",
            f"- unique_observations: {len(unique_observations)}",
            "",
            "## Evidence",
        ]
        lines.extend(f"- {item}" for item in unique_observations)
        return "\n".join(lines) + "\n"

    def promote_to_compiled_truth(
        self,
        vault_path: str | Path,
        page_name: str,
        content: str,
    ) -> Path:
        """Write a compiled-truth markdown page after lockdown.guard_write allows it."""
        target = Path(vault_path).expanduser().resolve(strict=False) / self._safe_page_name(page_name)
        ok, reason = guard_write(target)
        if not ok:
            raise PermissionError(reason)

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    @property
    def episodes(self) -> tuple[Episode, ...]:
        """Expose accumulated episodes without allowing mutation."""
        return tuple(self._episodes)

    def _normalize_episode(self, episode: Episode | Mapping[str, Any] | str) -> Episode:
        if isinstance(episode, Episode):
            return episode
        if isinstance(episode, str):
            return Episode(key=self._derive_key(episode), content=episode)
        if isinstance(episode, Mapping):
            content = str(episode.get("content") or episode.get("text") or "")
            key = str(episode.get("key") or episode.get("topic") or self._derive_key(content))
            source = str(episode.get("source") or "runtime")
            weight = int(episode.get("weight") or 1)
            if not content.strip():
                raise ValueError("episode content is required")
            return Episode(key=key, content=content, source=source, weight=max(1, weight))
        raise TypeError("episode must be Episode, mapping, or string")

    @staticmethod
    def _derive_key(content: str) -> str:
        words = re.findall(r"[A-Za-z0-9가-힣]+", content.lower())
        if not words:
            return "untitled"
        return "-".join(words[:6])

    @staticmethod
    def _safe_page_name(page_name: str) -> str:
        stem = re.sub(r"[^A-Za-z0-9가-힣._-]+", "-", page_name.strip()).strip(".-")
        if not stem:
            raise ValueError("page_name must contain at least one safe character")
        if not stem.endswith(".md"):
            stem = f"{stem}.md"
        return stem


def accumulate_all(cycle: DreamCycle, episodes: Iterable[Episode | Mapping[str, Any] | str]) -> DreamCycle:
    """Convenience helper for batch ingestion jobs."""
    for episode in episodes:
        cycle.accumulate(episode)
    return cycle
