"""Map 10 council rounds into a 6-chapter MBB report structure."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence


@dataclass(frozen=True)
class RoundDigest:
    layer_id: str
    chapter_title: str
    key_claim: str
    body_claims: List[str] = field(default_factory=list)
    evidence_ref_ids: List[str] = field(default_factory=list)
    confidence: float = 0.0
    framework: Optional[str] = None


@dataclass(frozen=True)
class Chapter:
    chapter_no: int
    title: str
    lead_claim: str
    body_claims: List[str]
    source_layers: List[str]
    framework: Optional[str] = None
    confidence: float = 0.0
    scr: Optional[Dict[str, str]] = None


CHAPTER_TITLES: Dict[int, str] = {
    1: "Executive Summary",
    2: "시장 기회",
    3: "경쟁 환경",
    4: "사업 타당성",
    5: "리스크 및 대응",
    6: "권고안 및 로드맵",
}


LAYER_TO_CHAPTER: Dict[str, int] = {
    "L1": 2,
    "L3": 2,
    "L2": 3,
    "L4": 4,
    "L5": 5,
    "L9": 5,
    "L6": 6,
    "L7": 6,
    "L8": 6,
    "L10": 1,
}


class ChapterMapper:
    def __init__(
        self,
        layer_to_chapter: Optional[Mapping[str, int]] = None,
        chapter_titles: Optional[Mapping[int, str]] = None,
    ) -> None:
        self.layer_to_chapter = dict(layer_to_chapter or LAYER_TO_CHAPTER)
        self.chapter_titles = dict(chapter_titles or CHAPTER_TITLES)

    def map(self, rounds: Sequence[RoundDigest]) -> List[Chapter]:
        groups: Dict[int, List[RoundDigest]] = {chapter: [] for chapter in self.chapter_titles}
        for digest in rounds:
            chapter_no = self._chapter_for_layer(digest.layer_id)
            if chapter_no is not None:
                groups[chapter_no].append(digest)
        return [
            self._build_executive(groups.get(1, [])) if chapter_no == 1 else self._build_chapter(chapter_no, groups.get(chapter_no, []))
            for chapter_no in sorted(self.chapter_titles)
        ]

    def _chapter_for_layer(self, layer_id: str) -> Optional[int]:
        prefix = layer_id.split("_", 1)[0] if layer_id else ""
        return self.layer_to_chapter.get(prefix)

    def _build_chapter(self, chapter_no: int, digests: Sequence[RoundDigest]) -> Chapter:
        title = self.chapter_titles.get(chapter_no, f"Chapter {chapter_no}")
        if not digests:
            return Chapter(chapter_no, title, f"{title}: 추가 리서치 필요", [], [], confidence=0.0)
        primary = max(digests, key=lambda item: item.confidence)
        body: List[str] = []
        for digest in digests:
            if digest.key_claim and digest.key_claim != primary.key_claim:
                body.append(digest.key_claim)
            body.extend(digest.body_claims)
        return Chapter(
            chapter_no=chapter_no,
            title=title,
            lead_claim=primary.key_claim,
            body_claims=body,
            source_layers=[digest.layer_id for digest in digests],
            framework=next((digest.framework for digest in digests if digest.framework), None),
            confidence=sum(digest.confidence for digest in digests) / len(digests),
        )

    def _build_executive(self, digests: Sequence[RoundDigest]) -> Chapter:
        title = self.chapter_titles[1]
        if not digests:
            return Chapter(1, title, "Executive Summary: 추가 리서치 필요", [], [], scr={}, confidence=0.0)
        primary = digests[0]
        scr = _extract_scr(primary.key_claim, primary.body_claims)
        body = [
            f"[Situation] {scr['situation']}",
            f"[Complication] {scr['complication']}",
            f"[Resolution] {scr['resolution']}",
        ]
        return Chapter(
            chapter_no=1,
            title=title,
            lead_claim=scr["resolution"] or primary.key_claim,
            body_claims=[line for line in body if line.strip().split("] ", 1)[-1]],
            source_layers=[digest.layer_id for digest in digests],
            scr=scr,
            confidence=primary.confidence,
        )


def _extract_scr(key_claim: str, body_claims: Sequence[str]) -> Dict[str, str]:
    situation = body_claims[0] if len(body_claims) >= 1 else ""
    complication = body_claims[1] if len(body_claims) >= 2 else ""
    resolution = body_claims[2] if len(body_claims) >= 3 else key_claim
    return {"situation": situation, "complication": complication, "resolution": resolution}
