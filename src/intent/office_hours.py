#!/usr/bin/env python3
"""Office Hours (THINK 단계) — gstack /office-hours 패턴 차용.

사용자의 한 줄 리서치 토픽을 design doc + 대안 + premise validation으로 정밀화한다.
6 forcing questions를 stdlib만으로 적용하며, 외부 LLM 호출 없이 휴리스틱 + 사용자
입력의 텍스트 분석으로 동작한다 (council/eval-agent와 분리된 entry layer).

원본: https://github.com/garrytan/gstack
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

try:
    from src.safety.lockdown import aup_risk, redact
except Exception:  # pragma: no cover
    aup_risk = None  # type: ignore[assignment]
    redact = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Alternative:
    """대안 implementation/접근 — effort 맵 포함."""
    title: str
    summary: str
    effort: str  # "S" / "M" / "L"
    risk: str    # "low" / "med" / "high"
    why_consider: str = ""


@dataclass(frozen=True)
class DesignDoc:
    """6 forcing questions를 통과한 결과."""
    raw_input: str
    pain_root: str            # Q1: 표면 요구 vs 실제 pain
    contrary_framing: str     # Q2: 반대로 본다면?
    implicit_capabilities: List[str]  # Q3: 암묵적으로 필요한 능력
    challenged_premises: List[str]    # Q4: 도전된 전제
    alternatives: List[Alternative]   # Q5: 대안 2-3개
    effort_map_summary: str           # Q6: effort 종합
    aup_risk_score: float = 0.0
    redacted: bool = False

    def to_brief(self) -> str:
        """council ontology 입력으로 사용할 한 페이지 brief."""
        lines = [
            f"# Design Doc — {self.raw_input[:60]}",
            "",
            f"## Pain Root",
            self.pain_root,
            "",
            f"## Contrary Framing",
            self.contrary_framing,
            "",
            f"## Implicit Capabilities ({len(self.implicit_capabilities)})",
        ]
        for cap in self.implicit_capabilities:
            lines.append(f"- {cap}")
        lines += ["", "## Challenged Premises"]
        for p in self.challenged_premises:
            lines.append(f"- {p}")
        lines += ["", "## Alternatives"]
        for alt in self.alternatives:
            lines.append(
                f"- **{alt.title}** (effort={alt.effort}, risk={alt.risk}): {alt.summary}"
            )
        lines += ["", f"## Effort Summary", self.effort_map_summary]
        if self.aup_risk_score > 0.0:
            lines += ["", f"_AUP risk: {self.aup_risk_score:.2f}_"]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# OfficeHours
# ---------------------------------------------------------------------------
class OfficeHours:
    """6 forcing questions로 사용자 입력을 design doc로 변환.

    LLM 호출 없는 stdlib 휴리스틱이지만 council 진입 전 강제 reframing 게이트로
    작동해 "내가 뭘 묻고 싶은지 모호한 상태"를 차단한다.
    """

    # 표면 요구를 pain으로 reframing할 키워드 패턴
    SURFACE_PATTERNS = (
        ("어떻게", "사용자가 'X를 어떻게 하나'를 묻지만 진짜 pain은 'X 없이는 무엇이 막히나'일 가능성"),
        ("뭐가 좋아", "선택지 비교가 표면 — 실제는 'A vs B 중 무엇이 우리 제약에 맞나'"),
        ("가능해", "feasibility 질문 표면 — 실제는 'cost/risk/time 중 어떤 한도가 binding인가'"),
        ("최선", "best practice 검색 표면 — 실제는 '우리 컨텍스트의 실패 모드는 무엇인가'"),
        ("도와", "도구 요청 표면 — 실제는 '직접 풀려는 시도가 막힌 지점이 어디인가'"),
    )

    def reframe(self, user_input: str, redact_pii: bool = True) -> DesignDoc:
        """사용자 1줄 입력 → DesignDoc."""
        raw = user_input.strip()
        if not raw:
            raise ValueError("empty user_input — cannot reframe")

        # PII redaction
        was_redacted = False
        if redact_pii and redact is not None:
            try:
                redacted = redact(raw)
                if redacted != raw:
                    was_redacted = True
                    raw = redacted
            except Exception:
                pass

        # AUP risk 측정
        risk_score = 0.0
        if aup_risk is not None:
            try:
                risk_score = float(aup_risk(raw))
            except Exception:
                risk_score = 0.0

        return DesignDoc(
            raw_input=raw,
            pain_root=self._q1_pain_root(raw),
            contrary_framing=self._q2_contrary(raw),
            implicit_capabilities=self._q3_implicit_capabilities(raw),
            challenged_premises=self._q4_challenge_premises(raw),
            alternatives=self._q5_alternatives(raw),
            effort_map_summary=self._q6_effort_summary(raw),
            aup_risk_score=risk_score,
            redacted=was_redacted,
        )

    # ------------------------------------------------------------------
    # 6 forcing questions
    # ------------------------------------------------------------------
    def _q1_pain_root(self, text: str) -> str:
        for kw, framing in self.SURFACE_PATTERNS:
            if kw in text:
                return f"{framing} (트리거: '{kw}')"
        # default: 가장 긴 noun phrase를 pain의 객체로 추정
        words = [w for w in text.replace("?", "").split() if len(w) >= 2]
        focus = max(words, key=len, default=text[:40])
        return f"입력 텍스트에서 '{focus}'가 핵심 객체로 보임. 실제 pain은 이 객체의 _현재 부재로 인한 불편_ 또는 _존재로 인한 부작용_ 중 하나."

    def _q2_contrary(self, text: str) -> str:
        return (
            f"반대 프레이밍: '{text[:60]}...'를 _하지 않으면_ 무슨 일이 일어나는가? "
            "이 답이 명확하지 않다면 진짜 needed가 아니라 nice-to-have일 수 있음. "
            "또한 정반대 가설 (예: 'X가 도움이 안 된다')도 council에서 contrarian persona가 검증해야."
        )

    def _q3_implicit_capabilities(self, text: str) -> List[str]:
        caps: List[str] = []
        if any(k in text for k in ("비교", "vs", "vs.", "or", "또는")):
            caps.append("비교 기준의 명시적 정의 (X축, 가중치)")
        if any(k in text for k in ("최신", "2026", "지금", "현재")):
            caps.append("시점 명시적 정의 (cutoff date, freshness 기준)")
        if any(k in text for k in ("한국", "Korean", "국내", "AgTech", "농가")):
            caps.append("한국 도메인 grounding (Nemotron-Personas-Korea seed 활용 가능)")
        if any(k in text for k in ("리서치", "조사", "research", "분석")):
            caps.append("출처 신뢰도 메타데이터 (citation_grounder 게이트 통과)")
        if any(k in text for k in ("비용", "가격", "cost", "price", "ROI")):
            caps.append("정량 ROI 추정 (불확실성 분포 명시)")
        if not caps:
            caps.append("입력에서 암묵적 능력을 추출할 단서 부족 — 추가 질문 필요")
        return caps

    def _q4_challenge_premises(self, text: str) -> List[str]:
        challenges: List[str] = []
        # 단정적 표현 도전
        if any(k in text for k in ("반드시", "당연", "must", "분명")):
            challenges.append("단정적 어조 — 정말 그런가? 반례 1개 이상 council에서 검증.")
        # 외부 권위 의존
        if any(k in text for k in ("다들", "everyone", "everybody", "전부")):
            challenges.append("'모두가 그렇다' 가정 — 표본 편향 가능. 누가 그렇지 않은가?")
        # 시간성 가정
        if any(k in text for k in ("계속", "여전히", "아직도")):
            challenges.append("정적 가정 — 최근 N개월 변화는 반영했는가?")
        if not challenges:
            challenges.append("명시적으로 도전할 전제가 입력에 보이지 않음 — council의 contrarian persona가 발견 책임.")
        return challenges

    def _q5_alternatives(self, text: str) -> List[Alternative]:
        # 휴리스틱 3가지: scope expansion / hold scope / scope reduction (gstack CEO 4 mode 단순화)
        return [
            Alternative(
                title="좁게 가기 (Hold Scope)",
                summary=f"입력 그대로 — 가장 빠르게 답을 얻고 후속 라운드에서 확장",
                effort="S",
                risk="low",
                why_consider="Mode 2 첫 라운드 baseline. 후속 ratchet으로 score 증가 검증 가능.",
            ),
            Alternative(
                title="확장 (Scope Expansion)",
                summary="입력의 1단계 인접 토픽까지 — 교차 axis 발견 기회",
                effort="M",
                risk="med",
                why_consider="2개 이상 interest axis 교차 시 novelty score boost (program.md 정책).",
            ),
            Alternative(
                title="축소 + 가설 분기 (Reduction with branches)",
                summary="입력을 더 작은 sub-question 2-3개로 쪼개 병렬 council",
                effort="M",
                risk="low",
                why_consider="async branch fork-join 패턴 — 충돌 시 EvoAgentX MAP-Elites archive로 다양성 maintain.",
            ),
        ]

    def _q6_effort_summary(self, text: str) -> str:
        return (
            "권장 첫 진입: 'Hold Scope' (effort S, risk low) → 1 라운드 baseline 확보 → "
            "score < 70이면 'Scope Expansion' 또는 'Reduction with branches'로 전환. "
            "Git Ratchet으로 단조 증가 보장."
        )
