"""Framework Registry — Layer → Frameworks 매핑 + council prompt 가이드."""
from __future__ import annotations
from typing import Dict, List, Tuple


# Layer ID → list of (framework_name, schema_hint)
_LAYER_FRAMEWORKS: Dict[str, List[Tuple[str, str]]] = {
    "L1_market_sizing": [
        ("MECE Tree", "TAM → SAM → SOM 분해 + 각 segment 정의"),
    ],
    "L2_competitor_landscape": [
        ("Porter 5 Forces", "5 forces severity(low/med/high) + rationale + 출처"),
    ],
    "L3_customer_jtbd": [
        ("JTBD", "functional/emotional/social 3축 × {job, current_solution, "
                 "underperformance_gap}"),
    ],
    "L4_financial_model": [
        ("MECE Tree", "Revenue / Cost / Margin / Cash 4 가지 분해"),
    ],
    "L5_risk_scenario": [
        ("SWOT", "Threats 위주 + WT 방어 전략"),
    ],
    "L6_implementation_roadmap": [],
    "L7_governance_ops": [],
    "L8_metrics_kpi": [
        ("North Star Tree", "북극성 1개 + driver 5-7 (current/target/cadence/owner)"),
    ],
    "L9_counterargs_sensitivities": [
        ("SWOT", "Strengths/Weaknesses/Opportunities/Threats 균형 + TOWS"),
    ],
    "L10_executive_synthesis": [],
}


def frameworks_for_layer(layer_id: str) -> List[Tuple[str, str]]:
    """layer ID → [(framework_name, schema_hint), ...]"""
    return list(_LAYER_FRAMEWORKS.get(layer_id, []))


def framework_prompt_block(layer_id: str) -> str:
    """council prompt에 삽입할 framework 가이드 markdown.

    페르소나가 답변 JSON에 framework_output 필드를 채우도록 강제하는 hint.
    """
    fws = frameworks_for_layer(layer_id)
    if not fws:
        return ""

    lines = ["## 🧰 이 Layer에 적용할 Framework", ""]
    for name, hint in fws:
        lines += [f"- **{name}** — {hint}"]
    lines += [
        "",
        "답변 JSON에 `framework_output` 필드로 위 framework schema를 채워주세요. "
        "이 framework가 채워져야 다음 round 종합에서 cross-persona 비교가 가능합니다.",
    ]
    return "\n".join(lines)
