#!/usr/bin/env python3
"""Learnings Log — gstack /learn 패턴 차용 (institutional memory).

세션 간 누적되는 confidence-scored 패턴 저장소. JSONL append-only로
.omc/autoresearch/learnings.jsonl에 누적되어 다음 세션의 retro/setup이
prior-learning을 인용 가능하게 한다.

원본: https://github.com/garrytan/gstack — `~/.gstack/projects/$SLUG/learnings.jsonl`
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


DEFAULT_LOG = Path(".omc/autoresearch/learnings.jsonl")


@dataclass(frozen=True)
class Learning:
    """단일 learning 엔트리 — gstack 스키마 준수."""
    key: str            # 짧은 식별자 (예: "korean-agtech-farmer-grounding")
    insight: str        # 한 문장 결론
    confidence: float   # 0.0~1.0
    source: str         # council_id / paper / commit-sha 등
    project_slug: str = "muchanipo"
    timestamp: str = ""

    def to_jsonl_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "insight": self.insight,
            "confidence": float(self.confidence),
            "source": self.source,
            "project_slug": self.project_slug,
            "timestamp": self.timestamp or datetime.now(timezone.utc).isoformat(),
        }


class LearningsLog:
    """append-only learnings.jsonl 관리자.

    gstack 원본은 ~/.gstack/projects/$SLUG/ 인데, muchanipo는 .omc/autoresearch/
    런타임 디렉토리를 사용해 다른 muchanipo 인프라와 같은 곳에 누적.
    """

    def __init__(self, log_path: Optional[Path] = None) -> None:
        self.log_path = Path(log_path) if log_path is not None else DEFAULT_LOG

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------
    def add(
        self,
        key: str,
        insight: str,
        confidence: float = 0.7,
        source: str = "",
        project_slug: str = "muchanipo",
    ) -> Learning:
        """단일 learning 추가."""
        if not key.strip():
            raise ValueError("learning key cannot be empty")
        if not insight.strip():
            raise ValueError("learning insight cannot be empty")
        if not (0.0 <= confidence <= 1.0):
            raise ValueError(f"confidence must be 0.0~1.0, got {confidence}")

        learning = Learning(
            key=key.strip(),
            insight=insight.strip(),
            confidence=float(confidence),
            source=source.strip(),
            project_slug=project_slug,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(learning.to_jsonl_dict(), ensure_ascii=False) + "\n")
        return learning

    def add_batch(self, entries: Iterable[Mapping]) -> List[Learning]:  # type: ignore
        """여러 learning 일괄 추가."""
        added: List[Learning] = []
        for entry in entries:
            added.append(
                self.add(
                    key=str(entry.get("key", "")),
                    insight=str(entry.get("insight", "")),
                    confidence=float(entry.get("confidence", 0.7)),
                    source=str(entry.get("source", "")),
                    project_slug=str(entry.get("project_slug", "muchanipo")),
                )
            )
        return added

    # ------------------------------------------------------------------
    # Read / Search
    # ------------------------------------------------------------------
    def all(self) -> List[Learning]:
        """전체 learning 리스트 (최신순)."""
        if not self.log_path.exists():
            return []
        learnings: List[Learning] = []
        with self.log_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                learnings.append(
                    Learning(
                        key=d.get("key", ""),
                        insight=d.get("insight", ""),
                        confidence=float(d.get("confidence", 0.0)),
                        source=d.get("source", ""),
                        project_slug=d.get("project_slug", "muchanipo"),
                        timestamp=d.get("timestamp", ""),
                    )
                )
        return list(reversed(learnings))  # 최신순

    def search(
        self,
        query: str,
        min_confidence: float = 0.0,
        limit: int = 10,
    ) -> List[Learning]:
        """key 또는 insight에 query 부분 매칭 + confidence 필터."""
        q = query.strip().lower()
        results: List[Learning] = []
        for l in self.all():
            if l.confidence < min_confidence:
                continue
            haystack = f"{l.key} {l.insight}".lower()
            if not q or q in haystack:
                results.append(l)
                if len(results) >= limit:
                    break
        return results

    def prune_stale(self, max_entries: int = 500) -> int:
        """오래된 entry 잘라내기 — 최신 max_entries만 보존."""
        all_learnings = self.all()  # 최신순
        if len(all_learnings) <= max_entries:
            return 0
        kept = all_learnings[:max_entries]
        removed = len(all_learnings) - len(kept)
        # 다시 시간순(오래된→최신)으로 저장
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("w", encoding="utf-8") as f:
            for l in reversed(kept):
                f.write(json.dumps(l.to_jsonl_dict(), ensure_ascii=False) + "\n")
        return removed

    def export(self, dest: Path) -> int:
        """팀 공유용 export."""
        learnings = self.all()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("w", encoding="utf-8") as f:
            for l in reversed(learnings):  # 시간순으로 export
                f.write(json.dumps(l.to_jsonl_dict(), ensure_ascii=False) + "\n")
        return len(learnings)


# Mapping 임포트 (Python 3.8 호환)
try:
    from collections.abc import Mapping  # type: ignore
except ImportError:
    from typing import Mapping  # type: ignore
