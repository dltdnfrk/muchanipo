#!/usr/bin/env python3
"""Plan Review (PLAN 단계) — gstack /plan-{ceo,eng,design,devex}-review 패턴 차용.

Office Hours가 만든 DesignDoc을 4-perspective로 검토하고 consensus 게이트를 통과한
ConsensusPlan을 ontology 입력 형식으로 변환한다. autoplan()이 4 review를 묶어
일괄 실행 + consensus 측정 + gate 결정을 수행.

원본: https://github.com/garrytan/gstack docs/skills.md
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# Office Hours 산출물을 입력으로 받음
try:
    from .office_hours import DesignDoc, Alternative
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from office_hours import DesignDoc, Alternative  # type: ignore


# ---------------------------------------------------------------------------
# Review dataclasses
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CeoReview:
    """전략적 fit + 10-star vision (gstack /plan-ceo-review)."""
    mode: str  # "expansion" | "selective" | "hold" | "reduction"
    ten_star_vision: str
    strategic_fit: str
    opt_in_decisions: List[str]
    confidence: float  # 0.0~1.0


@dataclass(frozen=True)
class EngReview:
    """기술적 architecture lock-in + diagrams + test matrix."""
    architecture_summary: str
    data_flow: List[str]      # 단계별 흐름
    state_transitions: List[str]
    edge_cases: List[str]
    test_matrix: List[str]
    feasibility: str  # "easy" / "medium" / "hard" / "blocked"


@dataclass(frozen=True)
class DesignReview:
    """UX coherence + user journey."""
    user_journey: List[str]
    ux_principles: List[str]
    visual_coherence: str
    accessibility_notes: List[str]


@dataclass(frozen=True)
class DevexReview:
    """개발자 경험 — friction, debuggability, observability."""
    friction_points: List[str]
    debuggability_score: float  # 0.0~1.0
    observability_gaps: List[str]
    suggested_fixtures: List[str]


@dataclass(frozen=True)
class ConsensusPlan:
    """4-review aggregate + gate 결정."""
    design_doc: DesignDoc
    ceo: CeoReview
    eng: EngReview
    design: DesignReview
    devex: DevexReview
    consensus_score: float          # 0.0~1.0
    gate_passed: bool
    gate_reason: str
    ontology_seed: Dict[str, Any]   # council ontology 입력 직접 사용 가능

    def to_ontology(self) -> Dict[str, Any]:
        """council Wave dispatch에 그대로 넣을 수 있는 ontology dict."""
        return dict(self.ontology_seed)


# ---------------------------------------------------------------------------
# PlanReview
# ---------------------------------------------------------------------------
class PlanReview:
    """4-perspective review + autoplan consensus 게이트."""

    def __init__(self, consensus_threshold: float = 0.6) -> None:
        self.consensus_threshold = float(consensus_threshold)

    # ------------------------------------------------------------------
    # Individual reviews
    # ------------------------------------------------------------------
    def ceo_review(self, doc: DesignDoc) -> CeoReview:
        """gstack /plan-ceo-review — taste gate, 10-star vision."""
        # 4 modes: 입력의 길이 + premises 수에 따라 결정
        challenged = len(doc.challenged_premises)
        caps = len(doc.implicit_capabilities)
        if challenged >= 2 and caps >= 3:
            mode, conf = "expansion", 0.75
        elif challenged >= 1 and caps >= 2:
            mode, conf = "selective", 0.65
        elif caps <= 1:
            mode, conf = "reduction", 0.55
        else:
            mode, conf = "hold", 0.7

        ten_star = (
            f"입력의 1-star: '{doc.raw_input[:50]}'. "
            f"10-star vision: 같은 토픽이지만 (a) 한국 grounded persona seed로 검증된, "
            f"(b) citation grounding 게이트 통과한, (c) vault에 영구 누적되는 _복리 효과_ "
            f"있는 리서치 결과. {len(doc.alternatives)}개 대안 중 best ROI 자동 선택."
        )
        strategic_fit = (
            f"NeoBio AgTech axis 정합도: {'높음' if any('AgTech' in c or '한국' in c for c in doc.implicit_capabilities) else '중간'}. "
            f"AI ML axis 정합도: {'높음' if any('citation' in c.lower() or '출처' in c for c in doc.implicit_capabilities) else '중간'}."
        )
        opt_ins = [
            f"alternative: {alt.title} ({alt.effort}/{alt.risk})"
            for alt in doc.alternatives
        ]
        return CeoReview(
            mode=mode,
            ten_star_vision=ten_star,
            strategic_fit=strategic_fit,
            opt_in_decisions=opt_ins,
            confidence=conf,
        )

    def eng_review(self, doc: DesignDoc, ceo: Optional[CeoReview] = None) -> EngReview:
        """gstack /plan-eng-review — architecture lock-in + diagrams forced."""
        # CEO mode가 expansion이면 더 무거운 architecture
        mode = ceo.mode if ceo else "hold"
        feasibility = {
            "expansion": "hard",
            "selective": "medium",
            "hold": "easy",
            "reduction": "easy",
        }.get(mode, "medium")

        data_flow = [
            "1. user_input → office_hours.reframe → DesignDoc",
            "2. DesignDoc → plan_review.autoplan → ConsensusPlan",
            "3. ConsensusPlan.ontology_seed → council Wave dispatch",
            "4. Council Report → eval-agent → citation_grounder gate",
            "5. PASS/UNCERTAIN/FAIL routing → vault / signoff queue",
            "6. retro.summarize → learnings.jsonl (다음 라운드 가설 시드)",
        ]
        state_transitions = [
            "DesignDoc.aup_risk_score >= 0.7 → BLOCK (lockdown)",
            "ConsensusPlan.gate_passed=False → SHORT_CIRCUIT (사용자에게 추가 질문)",
            "Council verdict=PASS but grounding_gate=False → DEMOTE to UNCERTAIN",
            "Mode 2 ratchet score 정체 3 라운드 → EARLY_STOP",
        ]
        edge_cases = [
            "사용자 입력이 빈 문자열 → ValueError",
            "Korea seed 부재 → KoreaPersonaSampler fallback 합성",
            "lockdown 모듈 부재 → optional skip (graceful)",
            "ontology 빈 roles → default ['evidence_reviewer']",
        ]
        test_matrix = [
            "test_office_hours.py (9 tests)",
            "test_plan_review.py (이번 commit, 7+ tests 예정)",
            "test_persona_generator.py (5 tests, seed 통합 포함)",
            "test_citation_grounder.py (12 tests, 회귀 방어)",
        ]
        return EngReview(
            architecture_summary=(
                f"intent layer (THINK/PLAN/REFLECT) → council layer (Wave/persona) → "
                f"eval layer (rubric+grounder+bias) → hitl layer (signoff) → "
                f"wiki layer (vault+dream-cycle). 6단계 단방향 layering, 순환 의존 없음."
            ),
            data_flow=data_flow,
            state_transitions=state_transitions,
            edge_cases=edge_cases,
            test_matrix=test_matrix,
            feasibility=feasibility,
        )

    def design_review(self, doc: DesignDoc) -> DesignReview:
        """gstack /plan-design-review — UX coherence."""
        journey = [
            "1. 사용자 한 줄 토픽 입력 (Mode 2 trigger)",
            "2. office_hours가 6 forcing questions 제시 → design doc 자동 생성",
            "3. 사용자가 design doc 검토 (옵션, 자동 진행도 가능)",
            "4. autoplan이 4-review 일괄 실행 → consensus 보고",
            "5. council Wave 동안 진행 상황 알림 (cron 또는 메신저)",
            "6. 결과 도착 시 PASS/UNCERTAIN HTML 리포트 자동 열기",
            "7. UNCERTAIN signoff queue를 채팅 인터페이스로 (Hermes/Klock 패턴)",
        ]
        principles = [
            "한 화면 = 한 결정 (사용자 입력은 항상 짧게)",
            "결과 grounded (가짜 evidence 차단 — citation_grounder)",
            "복리 효과 시각화 (vault 페이지 수 증가, index.md 줄 수)",
            "Silent Mode 지원 (밤에 자율 진행 시 한 줄 로그만)",
        ]
        a11y = [
            "한국어 우선 — 영문 reference도 한국어 요약 동반",
            "고령 사용자 (현장 농가) 대응: 필수 결정만 ✅/❌ 단순화",
        ]
        return DesignReview(
            user_journey=journey,
            ux_principles=principles,
            visual_coherence=(
                f"입력 1줄 → design doc 1페이지 → consensus plan 1페이지 → council report 1페이지 → "
                f"vault page 1개. 각 단계는 _한 페이지 안에 끝_."
            ),
            accessibility_notes=a11y,
        )

    def devex_review(self, doc: DesignDoc, eng: Optional[EngReview] = None) -> DevexReview:
        """gstack /plan-devex-review — developer experience."""
        friction = [
            "Mode 2 첫 진입에서 사용자 한 줄만으로는 정밀도 부족 → office_hours가 정정",
            "Council Wave 도중 디버깅 어려움 → iteration_hooks (C20)에 pre/post round 콜백",
            "데이터 적재 (Nemotron 1.9GB) 한 번 다운로드 부담 → sample500 commit으로 baseline 확보",
            "skill 변경 시 LLM 비결정성 → tests/test_skill_paths.py가 호출 경로 검증",
        ]
        debugability = 0.75 if eng and eng.feasibility in {"easy", "medium"} else 0.55
        gaps = [
            "Council 라운드 간 token 비용 누적 그래프 (현재 cost_trace framework만)",
            "lockdown audit log 시각화 (jsonl tail만 가능, dashboard 부재)",
            "vault dream-cycle 승격 이벤트 알림 (cron 결과 가시화 부재)",
        ]
        fixtures = [
            "tests/fixtures/sample_council_report_v2.json — 기본 PASS 케이스",
            "tests/fixtures/sample_council_report_with_unsupported.json — 강등 케이스",
            "vault/personas/seeds/korea/agtech-farmers-sample500.jsonl — Korea grounded 500",
        ]
        return DevexReview(
            friction_points=friction,
            debuggability_score=debugability,
            observability_gaps=gaps,
            suggested_fixtures=fixtures,
        )

    # ------------------------------------------------------------------
    # autoplan — 4-review 일괄 + consensus 게이트
    # ------------------------------------------------------------------
    def autoplan(self, doc: DesignDoc) -> ConsensusPlan:
        """4 review를 순차 실행하고 consensus 게이트 결정."""
        ceo = self.ceo_review(doc)
        eng = self.eng_review(doc, ceo=ceo)
        design = self.design_review(doc)
        devex = self.devex_review(doc, eng=eng)

        # consensus_score: 4 review의 confidence 신호 평균
        signals = [
            ceo.confidence,
            {"easy": 0.85, "medium": 0.65, "hard": 0.45, "blocked": 0.1}.get(eng.feasibility, 0.5),
            0.7 if len(design.user_journey) >= 5 else 0.5,
            devex.debuggability_score,
        ]
        consensus = sum(signals) / len(signals)

        # gate
        if doc.aup_risk_score > 0.7:
            gate_passed, reason = False, f"aup_risk={doc.aup_risk_score:.2f} > 0.7"
        elif consensus < self.consensus_threshold:
            gate_passed, reason = False, f"consensus={consensus:.2f} < {self.consensus_threshold}"
        elif eng.feasibility == "blocked":
            gate_passed, reason = False, "eng feasibility=blocked"
        else:
            gate_passed, reason = True, "all signals OK"

        # ontology seed for council
        ontology_seed = self._build_ontology(doc, ceo, eng)

        return ConsensusPlan(
            design_doc=doc,
            ceo=ceo,
            eng=eng,
            design=design,
            devex=devex,
            consensus_score=consensus,
            gate_passed=gate_passed,
            gate_reason=reason,
            ontology_seed=ontology_seed,
        )

    def _build_ontology(
        self,
        doc: DesignDoc,
        ceo: CeoReview,
        eng: EngReview,
    ) -> Dict[str, Any]:
        """ConsensusPlan을 council ontology 형식으로 변환."""
        roles = []
        # mode 기반 default roles
        if ceo.mode in {"expansion", "selective"}:
            roles += ["topic_owner", "evidence_reviewer", "contrarian"]
        else:
            roles += ["topic_owner", "evidence_reviewer"]
        # Korean domain 감지 시 농가 페르소나 추가
        if any("한국" in c or "Nemotron" in c for c in doc.implicit_capabilities):
            roles.append("agtech_farmer")
        # 비교 질문이면 두 측면 비교자 추가
        if "비교" in doc.pain_root or "선택지" in doc.pain_root:
            roles.append("comparison_judge")

        intents = [
            f"Topic: {doc.raw_input}",
            f"10-star: {ceo.ten_star_vision[:120]}",
            f"Pain root: {doc.pain_root[:80]}",
        ]
        # value_axes (C16 SCOPE)
        value_axes = {
            "time_horizon": "long" if ceo.mode == "expansion" else "mid",
            "risk_tolerance": 0.55 if ceo.mode in {"expansion", "selective"} else 0.35,
            "stakeholder_priority": ["primary_user", "evidence_quality", "domain_expert"],
            "innovation_orientation": 0.7 if ceo.mode == "expansion" else 0.45,
        }
        return {
            "roles": roles,
            "intents": intents,
            "allowed_tools": ["read_file", "search_web", "search_vault"],
            "required_outputs": ["consensus", "dissent", "recommendations", "evidence"],
            "value_axes": value_axes,
            "design_doc_brief": doc.to_brief(),
            "ceo_mode": ceo.mode,
            "feasibility": eng.feasibility,
        }


# ---------------------------------------------------------------------------
# C22-D: Rubric Coverage Gate
# ---------------------------------------------------------------------------
try:
    from .interview_rubric import InterviewRubric, CoverageStatus
except ImportError:  # pragma: no cover
    from interview_rubric import InterviewRubric, CoverageStatus  # type: ignore


def rubric_coverage_gate(
    rubric: "InterviewRubric",
    threshold: float = 0.75,
) -> Tuple[bool, str]:
    """Phase 0d 진입 직전 rubric coverage 검증 (Anthropic Interviewer 패턴).

    Args:
        rubric: Phase 0b에서 채워진 InterviewRubric
        threshold: 통과 임계 (기본 0.75 = 6 차원 중 5개 이상 covered)

    Returns:
        (passed, reason) — passed=False면 부족 차원 보완 probe 필요.

    근거:
    - Anthropic Interviewer planning → analysis 3단계
    - arXiv 2601.14798 Teacher-Educator stop signal (정량 임계)
    """
    rate = rubric.coverage_rate()
    if rate >= threshold:
        return True, f"Coverage {rate:.2f} ≥ {threshold:.2f} — Phase 0d 진입 OK"

    uncov = rubric.uncovered_dimension_ids()
    return False, (
        f"Coverage {rate:.2f} < {threshold:.2f} — 추가 probe 필요. "
        f"미충족 차원: {uncov}"
    )
