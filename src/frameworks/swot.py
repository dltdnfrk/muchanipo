"""SWOT — L9 counterargs / strategic positioning."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List


@dataclass
class SWOT:
    """SWOT — Strengths / Weaknesses / Opportunities / Threats."""
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)
    opportunities: List[str] = field(default_factory=list)
    threats: List[str] = field(default_factory=list)

    so_strategies: List[str] = field(default_factory=list)  # SO: 강점 + 기회
    wt_strategies: List[str] = field(default_factory=list)  # WT: 약점 보완 + 위협 회피

    def to_markdown(self) -> str:
        def block(label: str, items: List[str]) -> List[str]:
            if not items:
                return []
            return [f"### {label}"] + [f"- {x}" for x in items] + [""]

        lines = ["## SWOT Analysis", ""]
        lines += block("Strengths", self.strengths)
        lines += block("Weaknesses", self.weaknesses)
        lines += block("Opportunities", self.opportunities)
        lines += block("Threats", self.threats)
        if self.so_strategies or self.wt_strategies:
            lines += ["### TOWS Cross-Strategies", ""]
            lines += block("SO (Strengths × Opportunities)", self.so_strategies)
            lines += block("WT (Weaknesses × Threats — 방어)", self.wt_strategies)
        return "\n".join(lines).rstrip()
