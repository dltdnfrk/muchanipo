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
    """6 forcing questions (PRD-v2 §3.2)를 통과한 결과."""
    raw_input: str
    # Legacy fields kept for backward compatibility
    pain_root: str = ""
    contrary_framing: str = ""
    implicit_capabilities: List[str] = field(default_factory=list)
    challenged_premises: List[str] = field(default_factory=list)
    alternatives: List[Alternative] = field(default_factory=list)
    effort_map_summary: str = ""
    # PRD-v2 §3.2 formalized 6 Forcing Questions
    demand_reality: str = ""          # Q1
    status_quo: str = ""              # Q2
    desperate_specificity: str = ""   # Q3
    narrowest_wedge: str = ""         # Q4
    observation_surprise: str = ""    # Q5
    future_fit: str = ""              # Q6
    aup_risk_score: float = 0.0
    redacted: bool = False

    def to_brief(self) -> str:
        """council ontology 입력으로 사용할 한 페이지 brief."""
        lines = [
            f"# Design Doc — {self.raw_input[:60]}",
            "",
            "## Q1 Demand Reality",
            self.demand_reality or self.pain_root or "(no signal)",
            "",
            "## Q2 Status Quo",
            self.status_quo or self.contrary_framing or "(no signal)",
            "",
            "## Q3 Desperate Specificity",
            self.desperate_specificity or "(no signal)",
            "",
            "## Q4 Narrowest Wedge",
            self.narrowest_wedge or "(no signal)",
            "",
            "## Q5 Observation & Surprise",
            self.observation_surprise or "(no signal)",
            "",
            "## Q6 Future-Fit",
            self.future_fit or self.effort_map_summary or "(no signal)",
        ]
        if self.alternatives:
            lines += ["", "## Alternatives"]
            for alt in self.alternatives:
                lines.append(
                    f"- **{alt.title}** (effort={alt.effort}, risk={alt.risk}): {alt.summary}"
                )
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
            demand_reality=self._q1_demand_reality(raw),
            status_quo=self._q2_status_quo(raw),
            desperate_specificity=self._q3_desperate_specificity(raw),
            narrowest_wedge=self._q4_narrowest_wedge(raw),
            observation_surprise=self._q5_observation_surprise(raw),
            future_fit=self._q6_future_fit(raw),
            aup_risk_score=risk_score,
            redacted=was_redacted,
        )

    # ------------------------------------------------------------------
    # PRD-v2 §3.2 — 6 Forcing Questions (keyword-driven, stdlib only)
    # Each question is applied at most once (method call is idempotent).
    # ------------------------------------------------------------------

    # Q1 Demand Reality — keywords that signal existing demand
    Q1_DEMAND_KEYWORDS = ("돈", "지불", "구매", "가격", "비용", "매출", "수익", "ROI", "pay", "buy", "cost", "revenue", "subscription", "유료")
    # Q2 Status Quo — keywords about current state / existing solutions
    Q2_STATUS_QUO_KEYWORDS = ("현재", "지금", "사용", "쓰고", "기존", "대안", "existing", "current", "today", "use", "using", "alternative")
    # Q3 Desperate Specificity — keywords about target / persona / who
    Q3_SPECIFICITY_KEYWORDS = ("누구", "사용자", "고객", "타겟", "persona", "who", "user", "customer", "client", "구매자")
    # Q4 Narrowest Wedge — keywords about MVP / smallest / quick start
    Q4_WEDGE_KEYWORDS = ("MVP", "최소", "작은", "빠르게", "prototype", " minimally", "smallest", "quick", "fast", "pilot", "시범")
    # Q5 Observation & Surprise — keywords about learning / unexpected
    Q5_OBSERVATION_KEYWORDS = ("발견", "놀랍", "예상", "관찰", "배움", "surprise", "unexpected", "learned", "observed", "insight", "revelation")
    # Q6 Future-Fit — keywords about scope / exclusion / anti-roadmap
    Q6_FUTURE_FIT_KEYWORDS = ("범위", "안 할", "제외", "out of scope", "exclude", "not", "won\'t", "anti", "미포함", "의도적")

    def _q1_demand_reality(self, text: str) -> str:
        lower = text.lower()
        hits = [kw for kw in self.Q1_DEMAND_KEYWORDS if kw.lower() in lower]
        if hits:
            return (
                f"수요 신호 감지: {', '.join(hits[:3])}. "
                "'이미 돈을 내거나 행동으로 증명한 사람이 있는가?' — "
                "해당 키워드가 있으므로 이 토픽은 검증된 수요 영역일 가능성이 높음. "
                "구체적 증거(거래액, 가입자 수, waitlist)를 council에서 보강해야."
            )
        return (
            "수요 신호 미감지 — '이미 돈을 내거나 행동으로 증명한 사람이 있는가?' "
            "입력에 금전/행동 증거가 없으므로 이는 추측 수요일 수 있음. "
            "Council의 contrarian persona가 'nice-to-have vs must-have'를 검증해야."
        )

    def _q2_status_quo(self, text: str) -> str:
        lower = text.lower()
        hits = [kw for kw in self.Q2_STATUS_QUO_KEYWORDS if kw.lower() in lower]
        if hits:
            return (
                f"현재 상태 언급 감지: {', '.join(hits[:3])}. "
                "'지금 이 문제를 어떻게 해결하고 있는가?' — "
                "기존 솔루션의 존재를 인정하고 있으므로 차별화 포인트를 명시해야."
            )
        return (
            "'지금 이 문제를 어떻게 해결하고 있는가?' — "
            "현재 솔루션이 언급되지 않음. 진짜 경쟁자는 '현재의 행동'이다. "
            "Council에서 status quo를 끌어내는 리서치가 필요."
        )

    def _q3_desperate_specificity(self, text: str) -> str:
        lower = text.lower()
        hits = [kw for kw in self.Q3_SPECIFICITY_KEYWORDS if kw.lower() in lower]
        if hits:
            return (
                f"타겟 언급 감지: {', '.join(hits[:3])}. "
                "'이 문제로 절실하게 고통받는 한 사람의 이름을 댈 수 있는가?' — "
                "구체 인물이나 페르소나가 언급되었으나, '이름까지' 좁혔는지 검증 필요."
            )
        return (
            "'이 문제로 절실하게 고통받는 한 사람의 이름을 댈 수 있는가?' — "
            "타겟이 일반화되어 있음. 인터뷰 또는 페르소나 생성(HACHIMI)으로 구체화해야."
        )

    def _q4_narrowest_wedge(self, text: str) -> str:
        lower = text.lower()
        hits = [kw for kw in self.Q4_WEDGE_KEYWORDS if kw.lower() in lower]
        if hits:
            return (
                f"빠른 실행 언급 감지: {', '.join(hits[:3])}. "
                "'내일 출시할 수 있는 가장 작은 버전은 무엇인가?' — "
                "MVP 성향이 보이나, 실제로 24시간 내 검증 가능한 범위인지 council에서 체크."
            )
        return (
            "'내일 출시할 수 있는 가장 작은 버전은 무엇인가?' — "
            "범위 축소 의지가 보이지 않음. Scope reduction branch를 고려하거나, "
            "최소 검증 단위를 인터뷰에서 추가로 도출해야."
        )

    def _q5_observation_surprise(self, text: str) -> str:
        lower = text.lower()
        hits = [kw for kw in self.Q5_OBSERVATION_KEYWORDS if kw.lower() in lower]
        if hits:
            return (
                f"학습/발견 언급 감지: {', '.join(hits[:3])}. "
                "'사용자를 관찰하면서 예상치 못하게 배운 것은?' — "
                "실제 관찰 기반이 있으면 인용 근거로 삼고, 없으면 가설로 표시해야."
            )
        return (
            "'사용자를 관찰하면서 예상치 못하게 배운 것은? 진짜 만들고 있는 건 뭔가?' — "
            "빌더의 가정 vs 실제 사용자 행동 갭이 노출되지 않음. "
            "Council에서 '가장 큰 가정'을 contrarian이 공격해야."
        )

    def _q6_future_fit(self, text: str) -> str:
        lower = text.lower()
        hits = [kw for kw in self.Q6_FUTURE_FIT_KEYWORDS if kw.lower() in lower]
        if hits:
            return (
                f"범위 제한 언급 감지: {', '.join(hits[:3])}. "
                "'의도적으로 하지 않을 것은?' — "
                "anti-roadmap 요소가 보임. 이를 명시적으로 문서화하면 리서치 범위가 명확해짐."
            )
        return (
            "'의도적으로 하지 않을 것은? 범위 밖에 두는 것은?' — "
            "제품 경계가 불분명. 리서치가 산으로 갈 위험이 있으므로, "
            "out-of-scope 리스트를 인터뷰 후속 질문으로 도출해야."
        )


# ---------------------------------------------------------------------------
# C22-C: Pre-screen hook + reframe with context
# ---------------------------------------------------------------------------
import re as _re

# 잘 알려진 영문 약어 — 명확화 불필요 (화이트리스트)
_KNOWN_ACRONYMS: frozenset = frozenset({
    "AI", "ML", "LLM", "GPT", "API", "SDK", "URL", "HTTP", "JSON", "YAML",
    "SQL", "CPU", "GPU", "RAM", "OS", "UI", "UX", "PR", "CI", "CD", "QA",
    "PoC", "MVP", "B2B", "B2C", "SaaS", "ROI", "GTM", "KPI", "OKR", "RFP",
    "US", "EU", "UK", "JP", "KR", "PDF", "CSV", "XML", "HTML", "CSS", "JS",
    "TS", "DB", "RAG", "MCP", "TDD", "BDD",
})


@dataclass(frozen=True)
class PreScreenResult:
    """LangChain ODR clarification 1회 결과."""
    need_clarification: bool
    question: str = ""
    detected_terms: List[str] = field(default_factory=list)
    reason: str = ""


def _detect_unknown_acronyms(text: str) -> List[str]:
    """영문 대문자 3-7자 약어 중 화이트리스트 외 — 명확화 후보."""
    candidates = _re.findall(r"\b[A-Z][A-Z0-9]{2,6}\b", text or "")
    seen = set()
    unknown: List[str] = []
    for c in candidates:
        if c in _KNOWN_ACRONYMS:
            continue
        if c in seen:
            continue
        seen.add(c)
        unknown.append(c)
    return unknown


def pre_screen_hook(
    topic: str,
    history: Optional[Sequence[Dict[str, Any]]] = None,
) -> PreScreenResult:
    """LangChain ODR "ABSOLUTELY NECESSARY" 패턴 — 인터뷰 시작 전 1회 명확화.

    원칙:
    1. history에 이미 clarification 있으면 → 재질문 금지
    2. 영문 약어/줄임말 미지 용어 감지 → 명확화 트리거
    3. 그 외 → 명확화 불필요, 본 인터뷰로 진입

    Returns: PreScreenResult(need_clarification, question, detected_terms, reason)
    """
    history = history or []
    already_clarified = any(
        (msg.get("role") == "assistant" and "명확화" in str(msg.get("content", "")))
        or msg.get("type") == "clarification"
        for msg in history
    )
    if already_clarified:
        return PreScreenResult(
            need_clarification=False,
            reason="이미 1회 명확화 완료 — 재질문 억제 (LangChain ODR ABSOLUTELY NECESSARY)",
        )

    unknown = _detect_unknown_acronyms(topic)
    if unknown:
        terms = ", ".join(unknown[:3])
        return PreScreenResult(
            need_clarification=True,
            question=(
                f"'{terms}' 용어가 익숙하지 않은데 의미를 짧게 알려주실 수 있을까요?\n"
                "(약어가 명확하면 본 인터뷰로 바로 진입합니다.)"
            ),
            detected_terms=unknown,
            reason=f"영문 약어 미지 감지: {unknown}",
        )

    return PreScreenResult(
        need_clarification=False,
        reason="모호 용어 없음 — 본 인터뷰 진입 가능",
    )


def reframe_with_context(
    dim_id: str,
    topic: str,
    prev_answers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """LLMREI Interview Cookbook + show-me-the-prd — 다음 질문 동적 재구성.

    이전 답변(prev_answers)을 참조해 다음 질문 + 선택지를 보정.

    Returns: {"dim_id", "question", "options"} — AskUserQuestion에 그대로 전달 가능.
    """
    prev_answers = prev_answers or {}

    # interview_prompts에서 base options 가져오기 (지연 import — 순환 회피)
    try:
        from .interview_prompts import build_question_options
    except ImportError:  # pragma: no cover
        from interview_prompts import build_question_options  # type: ignore

    options = build_question_options(dim_id, topic, prev_answers)

    # base question text — dim별 PRD 톤
    base_questions: Dict[str, str] = {
        "Q1_research_question": "정확히 무엇을 알아내고 싶나요?",
        "Q2_purpose": "결과를 어디에 쓰시나요?",
        "Q3_context": "도메인 맥락은 어디까지인가요?",
        "Q4_known": "이미 알고 있는 게 있나요?",
        "Q5_deliverable": "산출물은 어떤 형태인가요?",
        "Q6_quality": "근거 품질 기준은? (Source A-D)",
    }
    question = base_questions.get(dim_id, dim_id)

    # 이전 답변 기반 보정 — Q3이 이전에 답해졌으면 Q4에 연결
    if dim_id == "Q4_known" and "Q3_context" in prev_answers:
        question = f"({prev_answers['Q3_context']} 맥락에서) 이미 알고 있는 게 있나요?"
    elif dim_id == "Q5_deliverable" and "Q2_purpose" in prev_answers:
        question = f"({prev_answers['Q2_purpose']} 목적에 맞춰) 어떤 형태의 산출물을 원하세요?"
    elif dim_id == "Q6_quality" and "Q5_deliverable" in prev_answers:
        question = f"({prev_answers['Q5_deliverable']} 산출물에 맞는) 근거 품질 기준은? (Source A-D)"

    return {"dim_id": dim_id, "question": question, "options": options}
