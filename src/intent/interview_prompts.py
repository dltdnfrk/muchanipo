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

try:  # pragma: no cover — optional import for tests that path-inject src/intent
    from .interview_rubric import InterviewRubric, RubricItem
except ImportError:  # noqa: F401
    from interview_rubric import InterviewRubric, RubricItem  # type: ignore


# ---------------------------------------------------------------------------
# Triage (Phase 0a)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class InterviewPlan:
    """Quick triage 결과 — Deep vs Quick interview 결정 + 보강할 차원 + Type."""
    mode: str  # "deep" | "quick"
    missing_dimensions: List[str]  # ex: ["timeframe", "domain", "evaluation"]
    rationale: str
    research_type: str = "exploratory"  # exploratory | comparative | analytical | predictive


# 핵심 차원 감지 키워드 (한국어 + 영문)
_DIM_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "timeframe": ("최신", "2026", "2025", "지금", "현재", "올해", "이번", "분기", "now", "recent", "latest"),
    "domain": ("한국", "한국어", "korean", "AgTech", "농가", "농업", "neobio", "MIRIVA", "의료", "농촌"),
    "evaluation": ("ROI", "비용", "가격", "cost", "지표", "정량", "수치", "기준", "score", "근거"),
    "comparison": ("비교", "vs", " or ", "또는", "대신", "차이", "더 좋은"),
    "monitoring": ("지속", "장기", "쌓아", "매일", "주간", "monitor", "feed", "trend", "꾸준히", "꾸준"),
    "specificity": ("이번 한 번", "한 번에", "결과 받기", "답 주세요", "결론"),
}


# Research Type 분류 키워드 (deep-research-query Phase 1 차용)
_TYPE_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "comparative": ("비교", "vs", " or ", "또는", "대신", "차이", "어느", "어떤 게 더", "compare"),
    "predictive": (
        "구축", "만들고", "만들기", "예측", "전망", "미래", "가능한지", "feasibility",
        "build", "design", "설계", "develop", "PoC",
    ),
    "analytical": (
        "ROI", "정량", "원인", "왜", "why", "분석", "지표", "수치", "metric", "근본",
        "cost", "비용 구조",
    ),
}


def classify_research_type(text: str) -> str:
    """deep-research-query Phase 1 — 4 type 분류.

    Returns: 'exploratory' | 'comparative' | 'analytical' | 'predictive'
    우선순위: comparative > predictive > analytical > exploratory(default)
    """
    if not text:
        return "exploratory"
    lowered = text.lower()
    for rtype in ("comparative", "predictive", "analytical"):
        if any(kw.lower() in lowered for kw in _TYPE_KEYWORDS[rtype]):
            return rtype
    return "exploratory"


def assess(user_input: str) -> InterviewPlan:
    """Phase 0a — Quick triage.

    입력이 짧고 모호하면 Deep interview (6 questions 차례로),
    길고 핵심 차원이 충분하면 Quick interview (부족한 차원만 1-2개 확인).
    """
    text = (user_input or "").strip()
    rtype = classify_research_type(text)
    if not text:
        return InterviewPlan(
            mode="deep",
            missing_dimensions=["timeframe", "domain", "evaluation"],
            rationale="empty input — full interview 필요",
            research_type=rtype,
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
            research_type=rtype,
        )

    if len(text) < 60 or len(detected) < 2:
        return InterviewPlan(
            mode="deep",
            missing_dimensions=missing or ["timeframe", "domain", "evaluation"],
            rationale=f"입력 {len(text)}자 / 명시 차원 {len(detected)}개 — Deep interview 필요",
            research_type=rtype,
        )

    return InterviewPlan(
        mode="quick",
        missing_dimensions=missing,
        rationale=f"입력 {len(text)}자 / {len(detected)}개 차원 명시 — Quick 확인만",
        research_type=rtype,
    )


# ---------------------------------------------------------------------------
# Forcing questions (Phase 0b — Deep mode)
# ---------------------------------------------------------------------------
def forcing_questions_korean() -> List[Dict[str, str]]:
    """리서치 토픽 정밀화 6 questions (PRD-style — 리서치 주제를 끄집어내는 톤).

    원본 gstack /office-hours는 YC 파운더 office hours 톤이라 비즈니스 의사결정에 치우침.
    사용자 요청에 맞춰 '리서치 brief'를 만드는 PRD 인터뷰 톤으로 재구성: 무엇/왜/맥락/이미 아는 것/
    산출물 형태/품질 기준. 이 6가지가 답해지면 council이 어긋나지 않고 사용자 의도대로 진행 가능.

    Claude이 사용자에게 그대로 출력해 한 번에 하나씩 답변을 받는다.
    """
    return [
        {
            "id": "Q1_research_question",
            "question": (
                "**Q1 / 6 — 정확히 무엇을 알아내고 싶으세요?**\n"
                "가능한 한 구체적인 질문으로 표현해주세요. 처음 던진 토픽보다 _한 단계 더 좁힌_ 질문이면 더 좋습니다.\n"
                "예시:\n"
                "- '한국 사과 농가 진단키트 가격 책정(2026 1분기 기준)'\n"
                "- 'LangGraph vs CrewAI — multi-agent council 구축에 어느 게 더 적합한가'\n"
                "- 'AI 에이전트 메모리 시스템 — 최근 6개월 주요 패턴'"
            ),
        },
        {
            "id": "Q2_purpose",
            "question": (
                "**Q2 / 6 — 답을 얻으면 무엇을 하실 거예요?**\n"
                "리서치 결과를 어디에 쓰시나요? 목적에 따라 결과 깊이/형태가 달라집니다.\n"
                "- 의사결정 (예: 어떤 도구 도입할지)\n"
                "- 글/문서 작성 (블로그, 보고서, 발표 자료)\n"
                "- 학습 / 이해 (개념·맥락 파악)\n"
                "- 추적 모니터링 (트렌드, 경쟁사)\n"
                "- 단순 호기심"
            ),
        },
        {
            "id": "Q3_context",
            "question": (
                "**Q3 / 6 — 어느 맥락 / 도메인이에요?**\n"
                "관련 도메인을 알려주시면 페르소나·평가 기준이 그쪽에 grounded됩니다.\n"
                "- NeoBio / AgTech / 한국 농업\n"
                "- AI / ML / 에이전트 시스템\n"
                "- Business strategy / 시장 분석\n"
                "- Tech stack / 개발 도구\n"
                "- 그 외 (자유 기술)\n"
                "그리고 **한국 시장 specific**인지, **글로벌 일반**인지도 알려주세요."
            ),
        },
        {
            "id": "Q4_known",
            "question": (
                "**Q4 / 6 — 이미 알고 계신 것은?**\n"
                "출발점을 알면 중복 검색을 피하고 새로운 인사이트에 집중할 수 있어요.\n"
                "- 들어본 키워드 / 읽은 자료\n"
                "- 알고 있는 경쟁사 / 기술 / 솔루션\n"
                "- 이미 검토한 옵션 / 폐기한 가설\n"
                "없으셔도 OK — '거의 모름'이라고만 답해도 됩니다."
            ),
        },
        {
            "id": "Q5_deliverable",
            "question": (
                "**Q5 / 6 — 어떤 형태의 답을 원하세요?**\n"
                "결과물 형식이 명확할수록 council 산출물이 사용자 의도와 맞아요.\n"
                "- 한 줄 요약 + 핵심 포인트 3-5개\n"
                "- 비교표 (옵션 A vs B vs C)\n"
                "- 정량 수치 + 출처 (시장 규모 / 가격 / 비율)\n"
                "- 시간순 흐름 / 단계별 가이드\n"
                "- 권고 / 의사결정 옵션\n"
                "- 인사이트 정리 (학습용)"
            ),
        },
        {
            "id": "Q6_quality",
            "question": (
                "**Q6 / 6 — 품질·범위 기준은?**\n"
                "- **출처**: 학술 논문 우선 / 실무 블로그 OK / 모두 OK\n"
                "- **깊이**: 개요(5분 읽기) / 보통(15분) / 심층(전체 디테일)\n"
                "- **시점**: 최신만 / 최근 6개월 / 1년 / 무관\n"
                "- **신뢰도**: citation grounding 강하게 / 단순 참고 OK\n"
                "- **언어**: 한국어 우선 / 영문 reference OK / 모두"
            ),
        },
    ]


def quick_clarification_questions(missing_dims: Sequence[str]) -> List[Dict[str, str]]:
    """Quick mode — 부족한 차원만 짧게 확인 (최대 2개)."""
    pool: Dict[str, str] = {
        "timeframe": (
            "**확인 — 시점**\n"
            "언제 기준 데이터가 필요한가요? (최신만 / 최근 6개월 / 2026 1분기 / 무관)"
        ),
        "domain": (
            "**확인 — 도메인 / 맥락**\n"
            "어느 도메인에 grounded돼야 하나요? (한국 시장 specific / 글로벌 일반 / 특정 산업)"
        ),
        "evaluation": (
            "**확인 — 산출물 형태 + 품질**\n"
            "어떤 형태의 답을 원하세요? (요약 / 비교표 / 정량 수치 / 권고) 그리고 어느 깊이? (개요 / 심층)"
        ),
        "comparison": (
            "**확인 — 비교 축**\n"
            "비교할 후보들이 있다면 어떤 축으로 비교? (가격 / 정확도 / 시장 점유 / 안정성 / 사용성)"
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
    research_type: str = "exploratory"  # exploratory | comparative | analytical | predictive


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
    research_type: Optional[str] = None,
) -> ModeDecision:
    """Phase 0e — Mode 자동 라우팅.

    autonomous_loop (Mode 1): 지속적/장기적 모니터링 / 무한 누적이 의미 있는 토픽
    targeted_iterative (Mode 2): 단일 질문 / 한 번 깊이 / 명확한 결과 필요

    휴리스틱:
    - 지속/장기 키워드 hit → autonomous_loop
    - 단일/구체적 시점 키워드 hit → targeted_iterative
    - ceo.mode == "expansion" + alternatives 다수 → autonomous_loop 가산점
    - ceo.mode == "hold" / "reduction" → targeted_iterative 가산점
    - research_type=analytical/comparative → targeted_iterative +1 (단발 결과 적합)
    - research_type=predictive → autonomous_loop +1 (구축은 지속 학습)
    - research_type=exploratory → 중립 (default 흐름)
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

    # C23-B: research_type 시그널 — 명시 안 되면 user_input + qa_text에서 자동 분류
    rtype = (research_type or classify_research_type(full_text) or "exploratory").lower()
    rtype_auto_bonus = 0
    rtype_targeted_bonus = 0
    if rtype in {"analytical", "comparative"}:
        rtype_targeted_bonus = 1
        targeted_score += 1
    elif rtype == "predictive":
        rtype_auto_bonus = 1
        auto_score += 1
    # exploratory: 중립

    signals = {
        "monitoring_keywords": monitoring_hits,
        "specificity_keywords": specificity_hits,
        "ceo_mode_bonus_auto": auto_score - monitoring_hits * 2 - rtype_auto_bonus,
        "ceo_mode_bonus_targeted": targeted_score - specificity_hits * 2 - rtype_targeted_bonus,
        "research_type_bonus_auto": rtype_auto_bonus,
        "research_type_bonus_targeted": rtype_targeted_bonus,
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

    return ModeDecision(
        mode=mode,
        reason=reason,
        confidence=confidence,
        signals=signals,
        research_type=rtype,
    )


def format_mode_routing_decision(decision: ModeDecision) -> str:
    """Phase 0e 결과 한 줄 보고."""
    label = {
        "autonomous_loop": "🔁 Autonomous Loop (무한 누적, 백그라운드)",
        "targeted_iterative": "🎯 Targeted Iterative (10라운드 단발)",
    }.get(decision.mode, decision.mode)

    type_label = {
        "exploratory": "🔎 Exploratory (탐색)",
        "comparative": "⚖️ Comparative (비교)",
        "analytical": "📊 Analytical (분석)",
        "predictive": "🛠️ Predictive (구축/예측)",
    }.get(decision.research_type, decision.research_type)

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🧭 **Mode Routing 자동 결정** (Phase 0e)",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"→ **{label}**",
        f"  research_type: {type_label}",
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


# ---------------------------------------------------------------------------
# C22-B: Entropy-Greedy Question Routing + Dynamic Options
# ---------------------------------------------------------------------------
def select_next_question(rubric: "InterviewRubric") -> Optional["RubricItem"]:
    """arXiv 2510.27410 Nous greedy entropy 원칙.

    InterviewRubric.next_uncovered() wrapper — 미답변 차원 중 entropy 최대 선택.
    동률이면 정의 순서(Q1→Q6) 우선.
    """
    return rubric.next_uncovered()


# 토픽-맞춤 옵션 보정 휴리스틱 (LLM 호출 없이)
_DOMAIN_HINTS: Dict[str, Tuple[str, ...]] = {
    "agtech": ("농가", "농업", "AgTech", "MIRIVA", "병원체", "작물", "과수"),
    "ai_agent": ("에이전트", "agent", "council", "LLM", "GPT", "Claude"),
    "biotech": ("진단", "프로브", "형광", "biomarker", "분자", "lab-in-the-loop"),
    "saas": ("SaaS", "구독", "ARR", "MRR", "churn"),
}


def _detect_domain(topic: str) -> str:
    lowered = (topic or "").lower()
    for dom, kws in _DOMAIN_HINTS.items():
        if any(kw.lower() in lowered for kw in kws):
            return dom
    return "general"


def build_question_options(
    dim_id: str,
    topic: str,
    prev_answers: Optional[Mapping[str, str]] = None,
) -> List[Dict[str, str]]:
    """AskUserQuestion 도구용 토픽-맞춤 선택지 생성 (show-me-the-prd 패턴).

    Returns: [{"label": str, "description": str}, ...] — 마지막은 항상 "Other".
    Q6은 Source A-D 고정. 그 외는 토픽 도메인에 맞춘 4 옵션 + Other.
    """
    domain = _detect_domain(topic)

    # Q6: Source quality A-D 고정 (deep-research-query)
    if dim_id == "Q6_quality":
        return [
            {"label": "A급 — peer-review/공식 통계만",
             "description": "정량 강함, 느림 (학술 논문 + 공공기관)"},
            {"label": "B급 — 학술 + 산업 리포트",
             "description": "균형 (Gartner, McKinsey 등 + arXiv)"},
            {"label": "C급 — 위 + 블로그/뉴스",
             "description": "빠름 (테크 블로그·언론 포함)"},
            {"label": "D급 — 추정·논리 위주",
             "description": "가장 빠름 (1차 근사)"},
            {"label": "Other", "description": "직접 입력"},
        ]

    # Q5 deliverable: 산출 형태
    if dim_id == "Q5_deliverable":
        return [
            {"label": "1페이지 결정서",
             "description": "핵심 숫자 + 권고 (의사결정용)"},
            {"label": "10-20p 리서치 리포트",
             "description": "상세 분석 + 다이어그램"},
            {"label": "Slide deck",
             "description": "발표/IR/보고용"},
            {"label": "Obsidian vault 누적",
             "description": "지속 모니터링 — autonomous_loop 자동 라우팅"},
            {"label": "Other", "description": "직접 입력"},
        ]

    # Q2 purpose: 사용 목적
    if dim_id == "Q2_purpose":
        return [
            {"label": "내부 의사결정",
             "description": "다음 액션 선택 (도구/방향/투자)"},
            {"label": "외부 보고",
             "description": "투자자 IR / 정부 과제 / 파트너 제안"},
            {"label": "지속 모니터링",
             "description": "트렌드/경쟁사 추적 (vault 누적)"},
            {"label": "학습·이해",
             "description": "맥락 파악 / 멘탈 모델 구축"},
            {"label": "Other", "description": "직접 입력"},
        ]

    # Q3 context: 도메인 범위 — domain hint 반영
    if dim_id == "Q3_context":
        if domain == "agtech":
            return [
                {"label": "한국 단일 작물·병원체 한정",
                 "description": "예: 사과 화상병"},
                {"label": "한국 작물 전반",
                 "description": "다 작물·다 병원체"},
                {"label": "한국 + 글로벌 비교",
                 "description": "일본/유럽/미국"},
                {"label": "글로벌 일반",
                 "description": "지역 무관"},
                {"label": "Other", "description": "직접 입력"},
            ]
        if domain == "biotech":
            return [
                {"label": "단일 분자·플랫폼 한정",
                 "description": "특정 프로브/타겟"},
                {"label": "분자 클래스 전반",
                 "description": "유사 메커니즘 군"},
                {"label": "기술 + 시장 융합",
                 "description": "기술 + 산업 동향"},
                {"label": "자율과학 시스템 전반",
                 "description": "도메인 무관 SOTA"},
                {"label": "Other", "description": "직접 입력"},
            ]
        return [
            {"label": "특정 산업·제품 한정", "description": "한 도메인 깊게"},
            {"label": "산업 전반", "description": "여러 도메인 비교"},
            {"label": "한국 specific", "description": "지역 grounded"},
            {"label": "글로벌 일반", "description": "지역 무관"},
            {"label": "Other", "description": "직접 입력"},
        ]

    # Q1 research_question: 무엇을 알아내고 싶은가
    if dim_id == "Q1_research_question":
        return [
            {"label": "단일 결정·숫자",
             "description": "1개 답 (예: 적정 가격)"},
            {"label": "옵션 비교",
             "description": "A vs B vs C 비교표"},
            {"label": "구축 가능성·설계도",
             "description": "feasibility + 아키텍처"},
            {"label": "벤치마크·SOTA 매핑",
             "description": "현재 최고 사례 정리"},
            {"label": "Other", "description": "직접 입력"},
        ]

    # Q4 known: 이미 아는 것
    if dim_id == "Q4_known":
        return [
            {"label": "관련 도구·솔루션 일부 파악",
             "description": "이름·키워드 수준"},
            {"label": "내부 데이터·노하우 보유",
             "description": "이미 시도한 접근"},
            {"label": "결정 일부 완료",
             "description": "특정 옵션은 이미 폐기"},
            {"label": "거의 없음",
             "description": "처음부터 매핑 필요"},
            {"label": "Other", "description": "직접 입력"},
        ]

    # Default fallback
    return [
        {"label": "Other", "description": "직접 입력"},
    ]
