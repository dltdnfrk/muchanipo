#!/usr/bin/env python3
"""Interview Prompts (사용자 상담 entry phase) — gstack /office-hours 패턴.

사용자 한 줄 리서치 요청을 받아 Claude이 대화형으로 정밀화 → DesignDoc → ConsensusPlan
→ **Mode 자동 라우팅** (autonomous_loop / targeted_iterative)까지 흐르도록 돕는 헬퍼.

이 모듈은 stdlib only, LLM 호출 없음. Claude이 사용자에게 묻고 답을 받은 뒤 그 결과를
office_hours.reframe()/plan_review.autoplan()에 넘기는 사이의 중간 단계 도구들을 제공.

원본 영감: https://github.com/garrytan/gstack docs/skills.md (/office-hours,
/plan-ceo-review, /plan-eng-review)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Triage (Phase 0a)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class InterviewPlan:
    """Quick triage 결과 — Deep vs Quick interview 결정 + 보강할 차원."""
    mode: str  # "deep" | "quick"
    missing_dimensions: List[str]  # ex: ["timeframe", "domain", "evaluation"]
    rationale: str


# 핵심 차원 감지 키워드 (한국어 + 영문)
_DIM_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "timeframe": ("최신", "2026", "2025", "지금", "현재", "올해", "이번", "분기", "now", "recent", "latest"),
    "domain": ("한국", "한국어", "korean", "AgTech", "농가", "농업", "neobio", "MIRIVA", "의료", "농촌"),
    "evaluation": ("ROI", "비용", "가격", "cost", "지표", "정량", "수치", "기준", "score", "근거"),
    "comparison": ("비교", "vs", " or ", "또는", "대신", "차이", "더 좋은"),
    "monitoring": ("지속", "장기", "쌓아", "매일", "주간", "monitor", "feed", "trend", "꾸준히", "꾸준"),
    "specificity": ("이번 한 번", "한 번에", "결과 받기", "답 주세요", "결론"),
}


def assess(user_input: str) -> InterviewPlan:
    """Phase 0a — Quick triage.

    입력이 짧고 모호하면 Deep interview (6 questions 차례로),
    길고 핵심 차원이 충분하면 Quick interview (부족한 차원만 1-2개 확인).
    """
    text = (user_input or "").strip()
    if not text:
        return InterviewPlan(
            mode="deep",
            missing_dimensions=["timeframe", "domain", "evaluation"],
            rationale="empty input — full interview 필요",
        )

    # 차원 매칭
    detected: List[str] = []
    missing: List[str] = []
    for dim, keywords in _DIM_KEYWORDS.items():
        if dim in {"monitoring", "specificity"}:
            continue  # 이건 Mode routing에서 사용
        if any(kw.lower() in text.lower() for kw in keywords):
            detected.append(dim)
        else:
            missing.append(dim)

    # dimension count 우선 — 3개 이상 명시면 길이 무관 Quick
    # (한국어는 영문 대비 압축률 높아 짧아도 rich할 수 있음)
    if len(detected) >= 3:
        return InterviewPlan(
            mode="quick",
            missing_dimensions=missing,
            rationale=f"입력 {len(text)}자 / {len(detected)}개 차원 충분 — Quick 확인만",
        )

    if len(text) < 60 or len(detected) < 2:
        return InterviewPlan(
            mode="deep",
            missing_dimensions=missing or ["timeframe", "domain", "evaluation"],
            rationale=f"입력 {len(text)}자 / 명시 차원 {len(detected)}개 — Deep interview 필요",
        )

    return InterviewPlan(
        mode="quick",
        missing_dimensions=missing,
        rationale=f"입력 {len(text)}자 / {len(detected)}개 차원 명시 — Quick 확인만",
    )


# ---------------------------------------------------------------------------
# Forcing questions (Phase 0b — Deep mode)
# ---------------------------------------------------------------------------
def forcing_questions_korean() -> List[Dict[str, str]]:
    """gstack /office-hours 6 forcing questions를 한국어 자연어로.

    Claude이 사용자에게 그대로 출력해 한 번에 하나씩 답변을 받는다.
    """
    return [
        {
            "id": "Q1_pain_root",
            "question": (
                "**Q1 / 6 — 진짜 pain이 뭔가요?**\n"
                "지금 던진 토픽 그대로가 아니라, 이 질문이 안 풀리면 무엇이 막히세요? "
                "(예: 의사결정이 미뤄짐 / 다른 작업이 멈춤 / 단순 호기심)"
            ),
        },
        {
            "id": "Q2_contrary",
            "question": (
                "**Q2 / 6 — 반대로 보면?**\n"
                "정반대 가설(예: 'X가 도움이 안 된다' 또는 'Y가 사실은 더 낫다')도 검증해야 할까요? "
                "단순 확인이면 단방향, 의사결정 영향이면 양방향 권장."
            ),
        },
        {
            "id": "Q3_implicit_caps",
            "question": (
                "**Q3 / 6 — 결과에 무엇이 꼭 들어가야?**\n"
                "다음 중 어느 게 결과 평가에 결정적입니까? (복수 선택 OK)\n"
                "- 시점 명시(언제 기준 데이터?)\n"
                "- 한국 도메인 grounding (한국 농가/시장)\n"
                "- 출처 신뢰도(citation grounding)\n"
                "- 정량 ROI 추정\n"
                "- 다른 항목"
            ),
        },
        {
            "id": "Q4_premises",
            "question": (
                "**Q4 / 6 — 도전해야 할 전제는?**\n"
                "당신이 이미 사실로 두는 가정 중에서, council이 _반례_를 찾아야 할 게 있나요? "
                "(예: '한국 농가는 가격 민감' / '경쟁사 X는 따라잡기 어렵다')"
            ),
        },
        {
            "id": "Q5_alternatives",
            "question": (
                "**Q5 / 6 — Scope는?**\n"
                "다음 중 어느 진입이 좋습니까?\n"
                "- (A) Hold Scope: 토픽 그대로 좁게 1라운드 (가장 빠름)\n"
                "- (B) Scope Expansion: 인접 토픽까지 확장 (교차 axis 발견)\n"
                "- (C) Reduction with branches: 작은 sub-question 2-3개 병렬\n"
                "- (D) Autonomous loop: 끝까지 무한 누적 (vault에 쌓아가기)"
            ),
        },
        {
            "id": "Q6_effort",
            "question": (
                "**Q6 / 6 — 시간/깊이는?**\n"
                "결과를 언제까지, 어느 깊이로? (예: '30분 안에 1차' / '하루 안에 final' / '백그라운드 무한 누적')"
            ),
        },
    ]


def quick_clarification_questions(missing_dims: Sequence[str]) -> List[Dict[str, str]]:
    """Quick mode — 부족한 차원만 짧게 확인 (최대 2개)."""
    pool: Dict[str, str] = {
        "timeframe": (
            "**확인 1 — 시점**\n"
            "언제 기준 데이터가 필요하세요? (최신 / 2026 1분기 / 특정 시점)"
        ),
        "domain": (
            "**확인 1 — 도메인**\n"
            "한국 시장/농가에 specific하게 grounded돼야 하나요, 아니면 글로벌 일반론?"
        ),
        "evaluation": (
            "**확인 1 — 평가 기준**\n"
            "결과 quality 기준으로 무엇이 가장 중요한가요? (정량 ROI / 출처 신뢰도 / 다양한 관점)"
        ),
        "comparison": (
            "**확인 1 — 비교 축**\n"
            "비교할 후보들이 있다면 어떤 축으로 비교? (가격 / 정확도 / 시장 점유 / 안정성)"
        ),
    }
    questions = [{"id": f"clarify_{d}", "question": pool[d]} for d in missing_dims if d in pool]
    return questions[:2]


# ---------------------------------------------------------------------------
# Answer aggregation (Phase 0c 진입 직전)
# ---------------------------------------------------------------------------
def merge_answers_to_text(
    user_input: str,
    qa_pairs: Sequence[Mapping[str, str]],
) -> str:
    """사용자 답변들을 office_hours.reframe()이 받을 통합 텍스트로 변환.

    qa_pairs: [{"id": "Q1_pain_root", "answer": "..."}, ...]
    """
    parts: List[str] = [f"[원 요청] {user_input.strip()}"]
    for qa in qa_pairs or []:
        qid = str(qa.get("id", "")).strip()
        ans = str(qa.get("answer", "")).strip()
        if not ans:
            continue
        parts.append(f"[{qid}] {ans}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Review formatters (Phase 0c, 0d)
# ---------------------------------------------------------------------------
def format_designdoc_review(design_doc: Any) -> str:
    """DesignDoc을 사용자 confirm 받기 좋은 한 페이지 markdown.

    design_doc: src.intent.office_hours.DesignDoc 인스턴스
    """
    if hasattr(design_doc, "to_brief"):
        brief = design_doc.to_brief()
    else:
        brief = str(design_doc)

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "📋 **DesignDoc Review** (Phase 0c)",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        brief,
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "이 design doc이 의도와 맞나요?",
        "  ✅ **승인** — 다음 단계 (ConsensusPlan)로 진행",
        "  ✏️ **수정** — 어느 섹션을 수정할지 알려주세요",
        "  ❌ **다시** — Interview부터 다시",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    return "\n".join(lines)


def format_consensusplan_review(consensus_plan: Any) -> str:
    """ConsensusPlan 한 페이지 markdown."""
    lines = ["━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"]
    lines.append("📐 **ConsensusPlan Review** (Phase 0d)")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")

    ceo = getattr(consensus_plan, "ceo", None)
    eng = getattr(consensus_plan, "eng", None)
    score = getattr(consensus_plan, "consensus_score", 0.0)
    gate_passed = getattr(consensus_plan, "gate_passed", False)
    gate_reason = getattr(consensus_plan, "gate_reason", "")
    onto = getattr(consensus_plan, "ontology_seed", {}) or {}

    lines.append(f"**Consensus**: {score:.2f} ({'✅ gate passed' if gate_passed else '❌ ' + gate_reason})")
    lines.append("")
    if ceo:
        mode = getattr(ceo, "mode", "?")
        ten_star = getattr(ceo, "ten_star_vision", "")[:200]
        lines.append(f"**CEO 판단**: mode=**{mode}**")
        lines.append(f"_{ten_star}..._")
        lines.append("")
    if eng:
        feas = getattr(eng, "feasibility", "?")
        lines.append(f"**Eng**: feasibility=**{feas}**")
        edge_cases = getattr(eng, "edge_cases", []) or []
        if edge_cases:
            lines.append("Edge cases:")
            for ec in edge_cases[:3]:
                lines.append(f"  - {ec}")
        lines.append("")

    roles = onto.get("roles", []) or []
    if roles:
        lines.append(f"**Council 페르소나 roles**: {', '.join(roles)}")
    value_axes = onto.get("value_axes", {}) or {}
    if value_axes:
        lines.append(
            f"**Value axes**: time={value_axes.get('time_horizon')} "
            f"risk={value_axes.get('risk_tolerance')} "
            f"innovation={value_axes.get('innovation_orientation')}"
        )
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("이 plan으로 council 시작할까요?")
    lines.append("  ✅ **시작** → Mode Routing(Phase 0e)으로")
    lines.append("  ✏️ **수정** — 어느 부분 (CEO mode / roles / value_axes)?")
    lines.append("  ❌ **DesignDoc부터 다시**")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Mode Routing (Phase 0e) — autonomous_loop vs targeted_iterative 자동 결정
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ModeDecision:
    mode: str  # "autonomous_loop" | "targeted_iterative"
    reason: str
    confidence: float  # 0.0~1.0
    signals: Dict[str, int]  # 키워드 매칭 카운트


def _count_keywords(text: str, keywords: Sequence[str]) -> int:
    if not text:
        return 0
    low = text.lower()
    return sum(1 for kw in keywords if kw.lower() in low)


def route_mode(
    design_doc: Any,
    consensus_plan: Any,
    user_input: str,
    qa_text: str = "",
) -> ModeDecision:
    """Phase 0e — Mode 자동 라우팅.

    autonomous_loop (Mode 1): 지속적/장기적 모니터링 / 무한 누적이 의미 있는 토픽
    targeted_iterative (Mode 2): 단일 질문 / 한 번 깊이 / 명확한 결과 필요

    휴리스틱:
    - 지속/장기 키워드 hit → autonomous_loop
    - 단일/구체적 시점 키워드 hit → targeted_iterative
    - ceo.mode == "expansion" + alternatives 다수 → autonomous_loop 가산점
    - ceo.mode == "hold" / "reduction" → targeted_iterative 가산점
    - 둘 다 약하면 default targeted_iterative (저렴함, 한 번이라도 결과 보고)
    """
    full_text = " ".join([
        str(user_input or ""),
        str(qa_text or ""),
        getattr(design_doc, "raw_input", "") if design_doc else "",
        " ".join(getattr(design_doc, "implicit_capabilities", []) or []) if design_doc else "",
    ])

    monitoring_hits = _count_keywords(full_text, _DIM_KEYWORDS["monitoring"])
    specificity_hits = _count_keywords(full_text, _DIM_KEYWORDS["specificity"])

    # ceo mode 보조 가중치
    ceo = getattr(consensus_plan, "ceo", None)
    ceo_mode = getattr(ceo, "mode", "hold") if ceo else "hold"
    alternatives_count = len(getattr(design_doc, "alternatives", []) or []) if design_doc else 0

    auto_score = monitoring_hits * 2
    targeted_score = specificity_hits * 2

    if ceo_mode == "expansion" and alternatives_count >= 3:
        auto_score += 2
    elif ceo_mode in {"hold", "reduction"}:
        targeted_score += 2
    elif ceo_mode == "selective":
        # 중간 — 약간 targeted 쪽으로
        targeted_score += 1

    signals = {
        "monitoring_keywords": monitoring_hits,
        "specificity_keywords": specificity_hits,
        "ceo_mode_bonus_auto": auto_score - monitoring_hits * 2,
        "ceo_mode_bonus_targeted": targeted_score - specificity_hits * 2,
    }

    diff = auto_score - targeted_score
    total = auto_score + targeted_score

    if diff >= 2:
        mode = "autonomous_loop"
        reason = (
            f"지속/장기 모니터링 신호 강함 (auto={auto_score}, targeted={targeted_score}). "
            f"vault에 누적되는 무한 루프 권장."
        )
        confidence = min(0.95, 0.5 + diff * 0.1)
    elif diff <= -2:
        mode = "targeted_iterative"
        reason = (
            f"구체 단발 질문 신호 강함 (targeted={targeted_score}, auto={auto_score}). "
            f"10라운드 iterative deepening 권장."
        )
        confidence = min(0.95, 0.5 + abs(diff) * 0.1)
    else:
        # 모호 — default targeted_iterative (저비용 + 한 번 결과)
        mode = "targeted_iterative"
        if total == 0:
            reason = "결정적 신호 없음 — default로 단발 iterative (저비용, 결과 한 번)."
            confidence = 0.5
        else:
            reason = (
                f"신호 균형 (auto={auto_score} vs targeted={targeted_score}) — "
                f"default targeted (안전한 첫 진입)."
            )
            confidence = 0.55

    return ModeDecision(mode=mode, reason=reason, confidence=confidence, signals=signals)


def format_mode_routing_decision(decision: ModeDecision) -> str:
    """Phase 0e 결과 한 줄 보고."""
    label = {
        "autonomous_loop": "🔁 Autonomous Loop (무한 누적, 백그라운드)",
        "targeted_iterative": "🎯 Targeted Iterative (10라운드 단발)",
    }.get(decision.mode, decision.mode)

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🧭 **Mode Routing 자동 결정** (Phase 0e)",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"→ **{label}**",
        f"  confidence: {decision.confidence:.2f}",
        f"  근거: {decision.reason}",
        "",
        "신호 카운트:",
    ]
    for k, v in decision.signals.items():
        lines.append(f"  - {k}: {v}")
    lines += [
        "",
        "이대로 진행할까요?",
        "  ✅ **이 모드로 시작**",
        f"  ✏️ **다른 모드로** ({'targeted_iterative' if decision.mode == 'autonomous_loop' else 'autonomous_loop'})",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    return "\n".join(lines)
