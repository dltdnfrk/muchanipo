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
    from src.intent.interview_rubric import InterviewRubric, RubricItem  # type: ignore

from src.intent.planning_contract import planning_question_contract


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
    "domain": ("한국", "한국어", "korean", "글로벌", "global", "산업", "도메인", "분야", "시장", "지역", "region"),
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
    """Socratic ontology extraction questions for Deep Interview.

    Internal Q1..Q6 IDs are retained for the existing brief/planning contract,
    but visible copy must not ask a fixed PRD form. Each prompt should infer the
    user's real ask by clarifying entities, actors, relations, triggers, signals,
    workflows, constraints, evidence boundaries, and excluded meanings.
    """
    return [
        {
            "id": "Q1_research_question",
            "question": (
                "**핵심 개체·질문**\n"
                "이 요청에서 진짜로 고정해야 할 핵심 명사와 대상은 무엇인가요? "
                "누가/무엇을/어떤 상태에서/어떤 신호를 근거로/어떤 행동으로 바꾸는지 "
                "한 문장으로 좁혀주세요. 단순 주제명이 아니라 개체·행위·관계가 드러나야 합니다."
            ),
        },
        {
            "id": "Q2_purpose",
            "question": (
                "**해석 경계**\n"
                "같은 표현이 가리킬 수 있는 서로 다른 해석을 갈라볼게요. "
                "지금 1차로 묻는 것은 문제 구조, 판별해야 할 상태, 채택 조건, 대체 해석 중 무엇인가요? "
                "포함할 의미와 제외 의미를 함께 적어주세요."
            ),
        },
        {
            "id": "Q3_context",
            "question": (
                "**행위자·트리거·워크플로우**\n"
                "이 일이 실제로 발생하는 장면을 쪼개면, 핵심 행위자는 누구이고 어떤 트리거나 신호가 "
                "어떤 행동과 결과로 이어지나요? 사용자-상황-신호-행동-결과 관계를 구체적으로 적어주세요."
            ),
        },
        {
            "id": "Q4_known",
            "question": (
                "**정의·제약·참고근거**\n"
                "이미 알고 있다고 느끼지만 정의가 흔들리는 용어는 무엇인가요? 참고자료, 배경 지식, "
                "제약, 폐기한 가설이 있다면 적어주세요. 리서치 전에 고정해야 할 개념 2-3개가 핵심입니다."
            ),
        },
        {
            "id": "Q5_deliverable",
            "question": (
                "**개념 지도·관계 구조**\n"
                "이 요청을 개념 지도로 옮기면 어떤 엔티티, 속성, 관계, 흐름, 금지해야 할 오해가 필요할까요? "
                "나중에 문서나 기능으로 바뀌더라도 먼저 ontology map이 안정되어야 합니다."
            ),
        },
        {
            "id": "Q6_quality",
            "question": (
                "**증거 경계·반례 기준**\n"
                "어떤 증거가 나오면 이 개념 정의가 맞다/틀리다고 판단할 수 있나요? "
                "허용할 출처 범위, 최신성, 지역성, 정량 기준, 가장 강한 반례를 함께 정해주세요."
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
# Muchanipo는 범용 리서치 툴이므로 특정 vertical(농업/바이오/SaaS 등)을
# 코드에 하드코딩하지 않는다. 선택지는 모든 토픽에 적용 가능한 리서치 차원만 쓴다.


def build_question_options(
    dim_id: str,
    topic: str,
    prev_answers: Optional[Mapping[str, str]] = None,
) -> List[Dict[str, str]]:
    """AskUserQuestion 도구용 토픽-맞춤 선택지 생성.

    Returns: [{"label": str, "description": str}, ...] — 마지막은 항상 "Other".
    Q6은 Source A-D를 증거 경계 옵션으로 유지한다. 그 외는 범용
    ontology-extraction 차원 옵션 + Other.
    """
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

    # Q5: concept map and relation structure
    if dim_id == "Q5_deliverable":
        return [
            {"label": "Entity / Relation map",
             "description": "핵심 개체, 속성, 관계를 먼저 고정"},
            {"label": "Workflow / Trigger map",
             "description": "상황, 신호, 행동, 결과 흐름을 구조화"},
            {"label": "Evidence boundary table",
             "description": "허용 근거, 금지 추정, 반례 기준을 분리"},
            {"label": "Excluded meanings list",
             "description": "헷갈리는 용어와 의도적으로 제외할 의미"},
            {"label": "Obsidian vault ontology",
             "description": "누적 지식 그래프/노트로 저장"},
            {"label": "Other", "description": "직접 입력"},
        ]

    # Q2: interpretation boundary
    if dim_id == "Q2_purpose":
        return [
            {"label": "문제 구조 우선",
             "description": "누가 어떤 마찰을 겪는지 정의"},
            {"label": "판별 상태 우선",
             "description": "무엇을 감지/분류/측정해야 하는지 정의"},
            {"label": "채택 조건 우선",
             "description": "누가 시간·돈·권한을 써서 받아들이는 조건"},
            {"label": "대체 해석 비교",
             "description": "서로 다른 개념 정의나 관점을 분리"},
            {"label": "제외 의미 먼저",
             "description": "이 요청이 뜻하지 않는 범위를 명시"},
            {"label": "Other", "description": "직접 입력"},
        ]

    # Q3 context: 도메인 범위 — domain hint 반영
    if dim_id == "Q3_context":
        return [
            {"label": "특정 산업·제품 한정", "description": "한 도메인 깊게"},
            {"label": "산업 전반", "description": "여러 도메인 비교"},
            {"label": "한국 specific", "description": "지역 grounded"},
            {"label": "글로벌 일반", "description": "지역 무관"},
            {"label": "Other", "description": "직접 입력"},
        ]

    # Q1: core entity and question
    if dim_id == "Q1_research_question":
        return [
            {"label": "핵심 질문 좁히기",
             "description": "핵심 명사와 행위 관계를 한 문장으로 고정"},
            {"label": "행위자/대상 분리",
             "description": "누가 무엇에 대해 움직이는지 분리"},
            {"label": "신호/상태 정의",
             "description": "무엇을 근거로 판단하는지 명시"},
            {"label": "행동/결과 관계",
             "description": "관찰 이후 어떤 행동과 결과가 이어지는지 명시"},
            {"label": "제외 의미",
             "description": "비슷하지만 지금 묻지 않는 범위"},
            {"label": "Other", "description": "직접 입력"},
        ]

    # Q4: definitions, constraints, and references
    if dim_id == "Q4_known":
        return [
            {"label": "정의가 흔들리는 용어",
             "description": "먼저 고정해야 할 명사/범주"},
            {"label": "참고자료·배경 단서",
             "description": "이미 본 문서, 데이터, 현장 메모"},
            {"label": "제약·금지 범위",
             "description": "법무, 예산, 일정, 데이터, 윤리 제약"},
            {"label": "폐기한 가설",
             "description": "다시 묻지 않아야 할 해석"},
            {"label": "거의 없음",
             "description": "처음부터 개념 지도 작성 필요"},
            {"label": "Other", "description": "직접 입력"},
        ]

    # Default fallback
    return [
        {"label": "Other", "description": "직접 입력"},
    ]
