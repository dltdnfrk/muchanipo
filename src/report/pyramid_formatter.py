"""Top-down ordering for 6-chapter reports."""
from __future__ import annotations

import re
from dataclasses import replace
from typing import List, Sequence

from src.report.chapter_mapper import Chapter


_NUMBER_RX = re.compile(r"\d+(?:\.\d+)?\s*[%원$BMK]|\d{4}년|\d+(?:\.\d+)?[조억만천]")


class PyramidFormatter:
    def reorder(self, chapter: Chapter) -> Chapter:
        if chapter.chapter_no == 1 and chapter.scr is not None:
            return self._reorder_executive(chapter)
        return self._reorder_standard(chapter)

    def reorder_all(self, chapters: Sequence[Chapter]) -> List[Chapter]:
        return [self.reorder(chapter) for chapter in chapters]

    def _reorder_standard(self, chapter: Chapter) -> Chapter:
        seen = {chapter.lead_claim.strip()}
        deduped: List[str] = []
        for claim in chapter.body_claims:
            stripped = claim.strip()
            if stripped and stripped not in seen:
                seen.add(stripped)
                deduped.append(stripped)
        return replace(chapter, body_claims=sorted(deduped, key=lambda claim: (-_importance_score(claim), len(claim))))

    def _reorder_executive(self, chapter: Chapter) -> Chapter:
        scr = chapter.scr or {}
        ordered = []
        for label, key in (("Situation", "situation"), ("Complication", "complication"), ("Resolution", "resolution")):
            if scr.get(key):
                ordered.append(f"[{label}] {scr[key]}")
        remaining = [
            claim
            for claim in chapter.body_claims
            if claim.strip()
            and not claim.startswith(("[Situation]", "[Complication]", "[Resolution]"))
        ]
        return replace(chapter, body_claims=ordered + sorted(remaining, key=lambda claim: (-_importance_score(claim), len(claim))))


def _importance_score(claim: str) -> int:
    score = 0
    if _NUMBER_RX.search(claim):
        score += 3
    if any(token in claim for token in ("출처", "source", "according to", "보고서", "Report")):
        score += 2
    if any(token in claim for token in ("따라서", "결론", "권고", "must", "should", "recommend")):
        score += 2
    if len(claim) < 20:
        score -= 1
    return score
