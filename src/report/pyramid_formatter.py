"""PyramidFormatter — McKinsey Pyramid Principle 정렬.

PRD-v2 §7.4. opencode 트랙 보완.

원칙:
    1. 결론(lead_claim)이 가장 먼저 — 챕터의 첫 문장
    2. 근거(body_claims)는 신뢰도/중요도 내림차순
    3. 세부사항은 마지막
    4. 챕터 1(Executive Summary)은 SCR 블록 그대로 유지

stdlib only.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Iterable, List, Sequence

from src.report.chapter_mapper import Chapter


_NUMBER_RX = re.compile(r"\d+(?:\.\d+)?\s*[%원\$bBmMkK]|\d{4}년|\d+(?:\.\d+)?[조억만천]")


class PyramidFormatter:
    """챕터 내 문장을 Top-down으로 재정렬."""

    def reorder(self, chapter: Chapter) -> Chapter:
        """챕터의 lead_claim은 그대로, body_claims를 중요도 순으로 정렬.

        Chapter 1(SCR)은 Situation→Complication→Resolution 순서가
        유지되어야 하므로 별도 처리.
        """
        if chapter.chapter_no == 1 and chapter.scr is not None:
            return self._reorder_executive(chapter)
        return self._reorder_standard(chapter)

    def reorder_all(self, chapters: Sequence[Chapter]) -> List[Chapter]:
        return [self.reorder(c) for c in chapters]

    # ---- helpers ----

    def _reorder_standard(self, chapter: Chapter) -> Chapter:
        """일반 챕터: body를 (1) lead와 중복 제거, (2) 중요도 점수로 내림차순."""
        if not chapter.body_claims:
            return chapter

        seen = {chapter.lead_claim.strip()}
        deduped: List[str] = []
        for claim in chapter.body_claims:
            stripped = claim.strip()
            if stripped and stripped not in seen:
                seen.add(stripped)
                deduped.append(stripped)

        scored = sorted(
            deduped,
            key=lambda c: (-_importance_score(c), len(c)),
        )

        return replace(chapter, body_claims=scored)

    def _reorder_executive(self, chapter: Chapter) -> Chapter:
        """Chapter 1: SCR 3블록을 [S]→[C]→[R] 순으로 강제, 나머지는 부록."""
        scr = chapter.scr or {}
        ordered: List[str] = []
        if scr.get("situation"):
            ordered.append(f"[Situation] {scr['situation']}")
        if scr.get("complication"):
            ordered.append(f"[Complication] {scr['complication']}")
        if scr.get("resolution"):
            ordered.append(f"[Resolution] {scr['resolution']}")

        # SCR에 이미 들어간 텍스트는 빼고 나머지를 일반 정렬
        scr_texts = {
            scr.get("situation", "").strip(),
            scr.get("complication", "").strip(),
            scr.get("resolution", "").strip(),
        }
        remaining = [
            c for c in chapter.body_claims
            if c.strip() and c.strip() not in scr_texts
            # 이미 [Situation]..[Resolution] prefix 박힌 라인 제거
            and not c.startswith(("[Situation]", "[Complication]", "[Resolution]"))
        ]
        scored_remaining = sorted(
            remaining,
            key=lambda c: (-_importance_score(c), len(c)),
        )

        # Top-down: 결론(lead = Resolution) → SCR 3블록 → 부록
        return replace(chapter, body_claims=ordered + scored_remaining)


def _importance_score(claim: str) -> int:
    """문장 중요도 휴리스틱.

    정량 수치, 출처 인용, 강한 동사가 있으면 가중치 ↑.
    Range: 0~10 정도.
    """
    score = 0
    if _NUMBER_RX.search(claim):
        score += 3
    if any(t in claim for t in ("출처", "source", "according to", "보고서", "Report")):
        score += 2
    if any(t in claim for t in ("따라서", "결론", "권고", "must", "should", "recommend")):
        score += 2
    # 너무 짧은 줄은 페널티
    if len(claim) < 20:
        score -= 1
    return score
