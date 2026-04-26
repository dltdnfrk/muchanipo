#!/usr/bin/env python3
"""Retro (REFLECT 단계) — gstack /retro 패턴 차용.

Council 결과 + signoff 결과를 받아 "어떻게 했는가?" 회고를 자동 생성하고
LearningsLog에 confidence-scored entry를 누적한다.

원본: https://github.com/garrytan/gstack — `/retro` skill, learnings.jsonl 패턴
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

try:
    from .learnings_log import LearningsLog, Learning
except ImportError:
    from src.intent.learnings_log import LearningsLog, Learning  # type: ignore


@dataclass(frozen=True)
class Retrospective:
    """단일 council/Mode 2 라운드의 회고."""
    council_id: str
    topic: str
    verdict: str           # PASS / UNCERTAIN / FAIL / CRASH
    score: float
    rounds: int            # Mode 2면 라운드 수
    duration_minutes: float
    what_went_well: List[str]
    what_failed: List[str]
    surprises: List[str]
    follow_up_questions: List[str]
    learnings: List[Learning]  # 이미 LearningsLog에 add 된 결과

    def to_progress_entry(self) -> str:
        """progress.md에 append할 한 단락."""
        lines = [
            f"## Exp#{self.council_id}: {self.topic}",
            f"- Verdict: {self.verdict} ({self.score:.1f})",
            f"- Rounds: {self.rounds}, Duration: {self.duration_minutes:.1f}m",
        ]
        if self.what_went_well:
            lines.append(f"- 잘된 점: {'; '.join(self.what_went_well[:3])}")
        if self.what_failed:
            lines.append(f"- 실패한 점: {'; '.join(self.what_failed[:3])}")
        if self.surprises:
            lines.append(f"- 놀라움: {'; '.join(self.surprises[:2])}")
        if self.follow_up_questions:
            lines.append(f"- 후속 질문: {'; '.join(self.follow_up_questions[:3])}")
        if self.learnings:
            lines.append(f"- 누적된 learning {len(self.learnings)}개 (learnings.jsonl)")
        return "\n".join(lines)


class Retro:
    """Council 결과를 받아 회고 + LearningsLog 누적."""

    def __init__(self, log: Optional[LearningsLog] = None) -> None:
        self.log = log if log is not None else LearningsLog()

    def summarize(
        self,
        council_id: str,
        topic: str,
        verdict: str,
        score: float,
        eval_result: Optional[Mapping[str, Any]] = None,
        council_report: Optional[Mapping[str, Any]] = None,
        rounds: int = 1,
        duration_minutes: float = 0.0,
    ) -> Retrospective:
        """회고 생성 + learnings 자동 추출 + LearningsLog에 추가."""
        eval_result = eval_result or {}
        council_report = council_report or {}

        what_went_well = self._extract_wins(verdict, score, eval_result, council_report)
        what_failed = self._extract_fails(verdict, score, eval_result, council_report)
        surprises = self._extract_surprises(eval_result, council_report)
        follow_ups = self._extract_follow_ups(council_report)

        # learnings 자동 추출 + 누적
        learnings = self._derive_and_log_learnings(
            council_id=council_id,
            topic=topic,
            verdict=verdict,
            score=score,
            eval_result=eval_result,
        )

        return Retrospective(
            council_id=council_id,
            topic=topic,
            verdict=verdict,
            score=float(score),
            rounds=rounds,
            duration_minutes=float(duration_minutes),
            what_went_well=what_went_well,
            what_failed=what_failed,
            surprises=surprises,
            follow_up_questions=follow_ups,
            learnings=learnings,
        )

    # ------------------------------------------------------------------
    # Heuristic extractors (LLM 없이 stdlib)
    # ------------------------------------------------------------------
    def _extract_wins(
        self,
        verdict: str,
        score: float,
        eval_result: Mapping[str, Any],
        council_report: Mapping[str, Any],
    ) -> List[str]:
        wins: List[str] = []
        if verdict == "PASS":
            wins.append(f"verdict=PASS, total score {score:.1f}")
        if eval_result.get("grounding", {}).get("verified_claim_ratio", 0) >= 0.85:
            wins.append("citation grounding ≥ 0.85 (claim 1:1 검증 통과)")
        scores = eval_result.get("scores", {})
        for axis, val in scores.items():
            if isinstance(val, (int, float)) and val >= 9:
                wins.append(f"{axis} 축 {val}/10 (탁월)")
        personas = council_report.get("personas", [])
        if len(personas) >= 10:
            wins.append(f"페르소나 {len(personas)}명 (3-Layer Ontology 충실)")
        if not wins:
            wins.append("뚜렷한 강점 미감지 — baseline 통과 정도")
        return wins[:5]

    def _extract_fails(
        self,
        verdict: str,
        score: float,
        eval_result: Mapping[str, Any],
        council_report: Mapping[str, Any],
    ) -> List[str]:
        fails: List[str] = []
        if verdict == "FAIL":
            fails.append(f"verdict=FAIL ({score:.1f} < threshold)")
        elif verdict == "UNCERTAIN":
            fails.append(f"UNCERTAIN — signoff queue 진입")
        elif verdict == "CRASH":
            fails.append("CRASH — 다음 토픽으로 skip")

        grounding = eval_result.get("grounding", {})
        if grounding.get("unsupported_critical_claim_count", 0) > 0:
            fails.append(
                f"unsupported critical claim {grounding['unsupported_critical_claim_count']}건"
            )
        if grounding.get("verified_claim_ratio", 1.0) < 0.5:
            fails.append(f"verified_claim_ratio {grounding['verified_claim_ratio']} < 0.5")

        scores = eval_result.get("scores", {})
        for axis, val in scores.items():
            if isinstance(val, (int, float)) and val <= 3:
                fails.append(f"{axis} 축 {val}/10 (취약)")
        return fails[:5]

    def _extract_surprises(
        self,
        eval_result: Mapping[str, Any],
        council_report: Mapping[str, Any],
    ) -> List[str]:
        surprises: List[str] = []
        # consensus와 dissent 동시 존재 = 놀라움
        if council_report.get("consensus") and council_report.get("dissent"):
            dissent = str(council_report["dissent"])
            if len(dissent) > 200:
                surprises.append(f"강한 dissent 잔존 ({len(dissent)}자) — 표면 합의에도 반대 관점 살아있음")
        # confidence 분산
        personas = council_report.get("personas", [])
        if personas:
            confs = [p.get("confidence", 0) for p in personas if isinstance(p, dict)]
            if confs and (max(confs) - min(confs)) >= 0.5:
                surprises.append(f"페르소나 confidence spread {max(confs)-min(confs):.2f} — 의견 갈림")
        return surprises[:3]

    def _extract_follow_ups(
        self,
        council_report: Mapping[str, Any],
    ) -> List[str]:
        # open_questions 또는 dissent에서 추출
        oqs = council_report.get("open_questions", [])
        if isinstance(oqs, list):
            return [str(q) for q in oqs[:5] if str(q).strip()]
        dissent = council_report.get("dissent", "")
        if isinstance(dissent, str) and dissent.strip():
            # 의문문 단순 추출
            sentences = [s.strip() for s in dissent.split(".") if "?" in s]
            return sentences[:3]
        return []

    def _derive_and_log_learnings(
        self,
        council_id: str,
        topic: str,
        verdict: str,
        score: float,
        eval_result: Mapping[str, Any],
    ) -> List[Learning]:
        learnings: List[Learning] = []

        # learning 1: verdict + score
        confidence = {"PASS": 0.85, "UNCERTAIN": 0.55, "FAIL": 0.4, "CRASH": 0.2}.get(verdict, 0.5)
        learnings.append(
            self.log.add(
                key=f"{topic[:30]}-verdict",
                insight=f"{topic[:60]} → {verdict} ({score:.1f})",
                confidence=confidence,
                source=f"council:{council_id}",
            )
        )

        # learning 2: citation grounding 결과
        grounding = eval_result.get("grounding", {})
        if grounding:
            ratio = grounding.get("verified_claim_ratio", 0.0)
            crit = grounding.get("unsupported_critical_claim_count", 0)
            if ratio >= 0.85:
                insight = f"{topic[:50]}는 citation grounding 통과 (ratio {ratio:.2f})"
                conf = 0.85
            else:
                insight = f"{topic[:50]}는 grounding 약함 (ratio {ratio:.2f}, critical_unsupported {crit})"
                conf = 0.4
            learnings.append(
                self.log.add(
                    key=f"{topic[:30]}-grounding",
                    insight=insight,
                    confidence=conf,
                    source=f"citation_grounder:council:{council_id}",
                )
            )

        # learning 3: 가장 약한 축
        scores = eval_result.get("scores", {})
        if scores:
            weakest = min(scores.items(), key=lambda kv: kv[1] if isinstance(kv[1], (int, float)) else 999)
            if isinstance(weakest[1], (int, float)) and weakest[1] <= 5:
                learnings.append(
                    self.log.add(
                        key=f"{topic[:30]}-weakest-axis",
                        insight=f"가장 약한 축: {weakest[0]} ({weakest[1]}/10) — 다음 라운드에서 강화 필요",
                        confidence=0.7,
                        source=f"eval-agent:council:{council_id}",
                    )
                )

        return learnings
