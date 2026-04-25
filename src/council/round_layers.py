#!/usr/bin/env python3
"""Round Layers (C24) — Mode 2 10 round를 각 round 다른 깊이로 재정의.

문제: 현재 council-runner는 round 1~N을 같은 prompt 형태로 반복 → 같은 층
10번 토론. MBB-급 컨설팅 deck은 각 chapter가 다른 층(시장/경쟁/재무/리스크/...).
이 모듈은 round 번호 → layer mapping을 제공하고, 각 layer가 council prompt에
주입할 focus question·persona emphasis·evidence kind를 정의한다.

stdlib only. council-runner._generate_roundN_prompts()에서 호출.

근거:
- McKinsey SCR (Situation/Complication/Resolution) 패턴 + Recommendation
- BCG strategy deck 구조 (Market → Competition → Customer → Financial → ...)
- Anthropic 81k Interviewer planning 단계 (multi-axis coverage)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence


@dataclass(frozen=True)
class RoundLayer:
    """1 round = 1 layer = council deck의 1 chapter."""

    layer_id: str          # "L1_market_sizing" .. "L10_executive_synthesis"
    chapter_title: str     # MBB deck chapter 제목 (한국어)
    focus_question: str    # 이 round 페르소나가 답해야 할 핵심 질문
    emphasis_roles: List[str]  # 이 layer에서 가중치 높은 role 이름
    evidence_kinds: List[str]  # 필요한 출처 종류 (industry_report / academic / interview / market_data)
    success_signal: str    # 이 layer 성공 기준 (=eval rubric에 가중치 시프트)


# ---------------------------------------------------------------------------
# 10 Layers — MBB consulting deck 구조 차용
# ---------------------------------------------------------------------------
DEFAULT_LAYERS: List[RoundLayer] = [
    RoundLayer(
        layer_id="L1_market_sizing",
        chapter_title="시장 규모 + 컨텍스트",
        focus_question=(
            "이 토픽이 다루는 시장의 TAM/SAM/SOM, 성장률, 핵심 트렌드 3개. "
            "구체 숫자 + 출처."
        ),
        emphasis_roles=["industry_analyst", "market_researcher", "data_scientist"],
        evidence_kinds=["market_data", "industry_report", "government_stats"],
        success_signal="정량 수치 + 출처 ≥ 5개, TAM/SAM/SOM 분리 명시",
    ),
    RoundLayer(
        layer_id="L2_competitor_landscape",
        chapter_title="경쟁 지형",
        focus_question=(
            "직접/간접/대체 경쟁자 매핑. 각자 가격·점유·강점·약점. "
            "포지셔닝 매트릭스(2축) 제안."
        ),
        emphasis_roles=["industry_analyst", "competitive_intel", "ceo_advisor"],
        evidence_kinds=["industry_report", "company_filings", "press"],
        success_signal="경쟁자 5+ 명시, 2x2 포지셔닝 축 제안, 차별화 gap 발견",
    ),
    RoundLayer(
        layer_id="L3_customer_jtbd",
        chapter_title="고객 Jobs-To-Be-Done + 페르소나",
        focus_question=(
            "타겟 고객의 functional/emotional/social JTBD 분석. "
            "현재 hire하는 솔루션 + 그 솔루션의 underperformance gap."
        ),
        emphasis_roles=["agtech_farmer", "primary_user", "domain_expert", "ux_researcher"],
        evidence_kinds=["interview", "ethnography", "user_research"],
        success_signal="JTBD 3축 분리, hire vs fire 후보 명시, gap quantify",
    ),
    RoundLayer(
        layer_id="L4_financial_model",
        chapter_title="재무 모델 + Unit Economics",
        focus_question=(
            "Unit economics(CAC/LTV/payback/margin) 추정. 3-year P&L sketch. "
            "break-even 시점."
        ),
        emphasis_roles=["cfo_advisor", "finance_analyst", "ceo_advisor"],
        evidence_kinds=["financial_report", "benchmark_data", "internal_estimate"],
        success_signal="CAC/LTV/payback 3개 숫자 + 가정 명시, break-even 분기 단위",
    ),
    RoundLayer(
        layer_id="L5_risk_scenario",
        chapter_title="리스크 + 시나리오",
        focus_question=(
            "Top 5 리스크 (regulatory/tech/market/financial/execution). "
            "Best/Base/Worst 3 시나리오 + 각 확률·임팩트."
        ),
        emphasis_roles=["risk_analyst", "scenario_planner", "compliance_expert"],
        evidence_kinds=["regulatory_doc", "historical_precedent", "expert_opinion"],
        success_signal="리스크 5+ severity·likelihood 표, 3 시나리오 정량 분리",
    ),
    RoundLayer(
        layer_id="L6_implementation_roadmap",
        chapter_title="실행 로드맵 + 마일스톤",
        focus_question=(
            "0-3-6-12개월 마일스톤. 각 단계 deliverable·owner·gating criteria. "
            "Critical path 식별."
        ),
        emphasis_roles=["product_manager", "operations_lead", "engineering_lead"],
        evidence_kinds=["operational_data", "case_study", "internal_capability"],
        success_signal="4 phase × 마일스톤 명시, critical path 1개 강조",
    ),
    RoundLayer(
        layer_id="L7_governance_ops",
        chapter_title="거버넌스 + 운영 모델",
        focus_question=(
            "RACI / decision rights / escalation 경로. KPI 보고 cadence. "
            "Build vs Buy vs Partner 결정 기준."
        ),
        emphasis_roles=["coo_advisor", "operations_lead", "compliance_expert"],
        evidence_kinds=["org_chart_pattern", "case_study", "best_practice"],
        success_signal="RACI 매트릭스, KPI cadence, build/buy/partner 기준 3축",
    ),
    RoundLayer(
        layer_id="L8_metrics_kpi",
        chapter_title="성과 지표 + KPI 트리",
        focus_question=(
            "북극성 KPI 1개 + 그 driver 지표 5-7개 트리. "
            "측정 cadence, 목표값, 현재값 baseline."
        ),
        emphasis_roles=["data_scientist", "growth_analyst", "ops_metric_owner"],
        evidence_kinds=["benchmark_data", "internal_metric", "industry_norm"],
        success_signal="north star + driver tree 5+, 목표·baseline 정량",
    ),
    RoundLayer(
        layer_id="L9_counterargs_sensitivities",
        chapter_title="반론 + 민감도 분석",
        focus_question=(
            "이 권고에 대한 가장 강한 반론 3개 + 각 반박. "
            "주요 가정 ±20% 변동 시 결과 영향 (sensitivity)."
        ),
        emphasis_roles=["devil_advocate", "skeptic", "scenario_planner"],
        evidence_kinds=["counter_evidence", "sensitivity_calc"],
        success_signal="반론 3+ + 각 반박, 가정 sensitivity ≥ 3 수치",
    ),
    RoundLayer(
        layer_id="L10_executive_synthesis",
        chapter_title="Executive Summary + Recommendation",
        focus_question=(
            "전체 9 layer 통합 한 문장 권고. So-What 3개. "
            "다음 90일 의사결정 1개 명시."
        ),
        emphasis_roles=["ceo_advisor", "managing_partner", "principal"],
        evidence_kinds=["synthesis_only"],
        success_signal="권고 1줄, So-What 3개, 90일 의사결정 1개 (action verb)",
    ),
]


# ---------------------------------------------------------------------------
# Type-aware layer 가중치 (Phase 0e research_type 반영)
# ---------------------------------------------------------------------------
_TYPE_LAYER_BOOSTS: Dict[str, List[str]] = {
    "analytical": ["L4_financial_model", "L5_risk_scenario", "L8_metrics_kpi"],
    "comparative": ["L2_competitor_landscape", "L3_customer_jtbd",
                    "L9_counterargs_sensitivities"],
    "predictive": ["L6_implementation_roadmap", "L7_governance_ops"],
    "exploratory": [],  # 균형
}


def select_layer_for_round(
    round_num: int,
    total_rounds: int = 10,
    research_type: str = "exploratory",
    layers: Optional[Sequence[RoundLayer]] = None,
) -> RoundLayer:
    """round 번호 + research_type → 해당 layer 반환.

    기본 매핑: round N → layer N (1-indexed).
    total_rounds < 10이면 가장 중요한 N 개를 type 기반으로 선택.
    """
    layers = list(layers or DEFAULT_LAYERS)
    if round_num < 1:
        raise ValueError("round_num must be >= 1")

    # 10 round full mapping
    if total_rounds >= 10:
        idx = min(round_num - 1, len(layers) - 1)
        return layers[idx]

    # < 10 round: type 기반 우선 선택
    boosts = _TYPE_LAYER_BOOSTS.get(research_type, [])
    boosted = [l for l in layers if l.layer_id in boosts]
    rest = [l for l in layers if l.layer_id not in boosts]
    # L1 + L10은 항상 포함 (foundation + synthesis)
    must = [l for l in layers if l.layer_id in {"L1_market_sizing",
                                                  "L10_executive_synthesis"}]
    ordered = must + boosted + [l for l in rest if l not in must]
    selected = ordered[:total_rounds]
    idx = min(round_num - 1, len(selected) - 1)
    return selected[idx]


def layer_prompt_block(layer: RoundLayer) -> str:
    """council prompt에 삽입할 layer-specific guidance 블록 (markdown).

    _generate_roundN_prompts에서 호출.
    """
    lines = [
        f"## 📑 이 Round의 Chapter — {layer.chapter_title}",
        "",
        f"**Focus Question:** {layer.focus_question}",
        "",
        f"**필요 evidence:** {', '.join(layer.evidence_kinds)}",
        "",
        f"**강조 역할:** {', '.join(layer.emphasis_roles)} 페르소나의 의견을 가중",
        "",
        f"**성공 기준:** {layer.success_signal}",
        "",
        "이 chapter에 충실히 답하세요. 다른 layer 내용은 다음 round에서 다룹니다.",
    ]
    return "\n".join(lines)


def all_layer_ids() -> List[str]:
    return [l.layer_id for l in DEFAULT_LAYERS]
