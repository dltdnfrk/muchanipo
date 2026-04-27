"""ChapterMapper — 10 Council rounds (Bottom-up) → 6 MBB chapters (Top-down).

PRD-v2 §7.4 Dual Structure 핵심 컴포넌트.
opencode 트랙에서 누락된 모듈을 eval-council 트랙에서 보완.

매핑 규칙:
    L10        → Chapter 1 (Executive Summary, SCR 추출)
    L1 + L3    → Chapter 2 (시장 기회)
    L2         → Chapter 3 (경쟁)
    L4         → Chapter 4 (재무)
    L5 + L9    → Chapter 5 (리스크)
    L6+L7+L8   → Chapter 6 (로드맵)

stdlib only — 외부 LLM 호출 없음.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence


# ---- Inputs ----------------------------------------------------------------


@dataclass(frozen=True)
class RoundDigest:
    """Council 한 라운드 결과의 보고서용 다이제스트.

    council/schema RoundResult가 무겁다면 여기에 맞게 변환 후 주입.
    """

    layer_id: str  # "L1_market_sizing" 등 — 첫 토큰만 매칭에 사용 (L1, L2, ...)
    chapter_title: str  # 한국어 챕터 제목 (round_layers.RoundLayer.chapter_title)
    key_claim: str  # 라운드의 핵심 결론 (1-2문장)
    body_claims: List[str] = field(default_factory=list)  # 근거 목록
    evidence_ref_ids: List[str] = field(default_factory=list)
    confidence: float = 0.0
    framework: Optional[str] = None  # "Porter", "JTBD", ...


# ---- Outputs ---------------------------------------------------------------


@dataclass(frozen=True)
class Chapter:
    """MBB 6-chapter 보고서의 한 챕터."""

    chapter_no: int
    title: str
    lead_claim: str  # 첫 문장 = 핵심 주장 (Pyramid Principle)
    body_claims: List[str]
    source_layers: List[str]  # 출처 라운드 ID 목록 (audit trail)
    framework: Optional[str] = None
    confidence: float = 0.0
    scr: Optional[Dict[str, str]] = None  # Chapter 1만 사용: {situation, complication, resolution}


# ---- Mapping rules ---------------------------------------------------------


CHAPTER_TITLES: Dict[int, str] = {
    1: "Executive Summary",
    2: "시장 기회",
    3: "경쟁 환경",
    4: "사업 타당성",
    5: "리스크 및 대응",
    6: "권고안 및 로드맵",
}


# layer_prefix(L1, L2, ...) → chapter_no
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


# ---- Mapper ----------------------------------------------------------------


class ChapterMapper:
    """RoundDigest 시퀀스를 받아 6 chapters로 재포장."""

    def __init__(
        self,
        layer_to_chapter: Optional[Mapping[str, int]] = None,
        chapter_titles: Optional[Mapping[int, str]] = None,
    ) -> None:
        self.layer_to_chapter = dict(layer_to_chapter or LAYER_TO_CHAPTER)
        self.chapter_titles = dict(chapter_titles or CHAPTER_TITLES)

    def map(self, rounds: Sequence[RoundDigest]) -> List[Chapter]:
        """모든 라운드를 6 챕터로 매핑."""
        # Group rounds by chapter_no
        groups: Dict[int, List[RoundDigest]] = {ch: [] for ch in self.chapter_titles}
        for digest in rounds:
            ch_no = self._chapter_for_layer(digest.layer_id)
            if ch_no is None:
                continue
            groups[ch_no].append(digest)

        chapters: List[Chapter] = []
        for ch_no in sorted(self.chapter_titles):
            digests = groups.get(ch_no, [])
            if ch_no == 1:
                chapters.append(self._build_executive(digests))
            else:
                chapters.append(self._build_chapter(ch_no, digests))
        return chapters

    # ---- helpers ----

    def _chapter_for_layer(self, layer_id: str) -> Optional[int]:
        if not layer_id:
            return None
        prefix = layer_id.split("_", 1)[0]
        return self.layer_to_chapter.get(prefix)

    def _build_chapter(self, chapter_no: int, digests: Sequence[RoundDigest]) -> Chapter:
        title = self.chapter_titles.get(chapter_no, f"Chapter {chapter_no}")

        if not digests:
            return Chapter(
                chapter_no=chapter_no,
                title=title,
                lead_claim=f"({title}: 출처 라운드 없음 — 추가 리서치 필요)",
                body_claims=[],
                source_layers=[],
                framework=None,
                confidence=0.0,
            )

        # 가장 confidence 높은 round의 key_claim → lead_claim
        primary = max(digests, key=lambda d: d.confidence)
        lead = primary.key_claim or f"({title})"

        body: List[str] = []
        for d in digests:
            # 첫 줄: round의 key_claim
            if d.key_claim and d.key_claim != lead:
                body.append(d.key_claim)
            body.extend(d.body_claims)

        # 평균 confidence
        avg_conf = sum(d.confidence for d in digests) / len(digests)
        # 첫 framework 사용
        fw = next((d.framework for d in digests if d.framework), None)

        return Chapter(
            chapter_no=chapter_no,
            title=title,
            lead_claim=lead,
            body_claims=body,
            source_layers=[d.layer_id for d in digests],
            framework=fw,
            confidence=avg_conf,
        )

    def _build_executive(self, digests: Sequence[RoundDigest]) -> Chapter:
        """Chapter 1: SCR 프레임워크 추출.

        L10 (Executive Synthesis) 라운드의 body_claims를 3등분하여
        Situation / Complication / Resolution에 배치.
        """
        title = self.chapter_titles.get(1, "Executive Summary")

        if not digests:
            return Chapter(
                chapter_no=1,
                title=title,
                lead_claim="(Executive Summary: L10 라운드 없음)",
                body_claims=[],
                source_layers=[],
                scr={"situation": "", "complication": "", "resolution": ""},
                confidence=0.0,
            )

        primary = digests[0]  # L10은 보통 1개
        scr = _extract_scr(primary.key_claim, primary.body_claims)
        # lead = Resolution 우선 (Top-down: 결론부터)
        lead = scr.get("resolution") or primary.key_claim or "(Resolution 미정)"

        body: List[str] = []
        if scr.get("situation"):
            body.append(f"[Situation] {scr['situation']}")
        if scr.get("complication"):
            body.append(f"[Complication] {scr['complication']}")
        if scr.get("resolution"):
            body.append(f"[Resolution] {scr['resolution']}")

        # 추가 body_claims는 부록 형태로
        body.extend(primary.body_claims)

        return Chapter(
            chapter_no=1,
            title=title,
            lead_claim=lead,
            body_claims=body,
            source_layers=[d.layer_id for d in digests],
            scr=scr,
            confidence=primary.confidence,
        )


def _extract_scr(key_claim: str, body_claims: Sequence[str]) -> Dict[str, str]:
    """L10의 텍스트로부터 Situation/Complication/Resolution 추출.

    휴리스틱:
        1. body_claims 첫 3개를 순서대로 S/C/R로 매핑 (충분한 경우)
        2. 부족하면 빈 문자열로
        3. key_claim은 Resolution 보강 후보로 사용
    """
    s = body_claims[0] if len(body_claims) >= 1 else ""
    c = body_claims[1] if len(body_claims) >= 2 else ""
    r = body_claims[2] if len(body_claims) >= 3 else ""

    # Resolution이 비어있으면 key_claim으로 폴백
    if not r and key_claim:
        r = key_claim

    return {"situation": s, "complication": c, "resolution": r}
