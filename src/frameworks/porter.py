"""Porter 5 Forces — L2 competitor landscape framework."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ForceLevel:
    """1개 force의 평가 — low/med/high + rationale + 출처."""
    severity: str  # "low" | "med" | "high"
    rationale: str
    sources: List[str] = field(default_factory=list)

    def __post_init__(self):
        if self.severity not in {"low", "med", "high"}:
            raise ValueError(f"severity must be low/med/high, got {self.severity}")


@dataclass
class Porter5Forces:
    """Michael Porter 5 Forces — 경쟁 강도 분석."""
    threat_new_entrants: ForceLevel
    threat_substitutes: ForceLevel
    bargaining_buyers: ForceLevel
    bargaining_suppliers: ForceLevel
    rivalry: ForceLevel

    summary: str = ""

    def to_markdown(self) -> str:
        forces = [
            ("신규 진입 위협", self.threat_new_entrants),
            ("대체재 위협", self.threat_substitutes),
            ("구매자 교섭력", self.bargaining_buyers),
            ("공급자 교섭력", self.bargaining_suppliers),
            ("기존 경쟁자 간 경쟁", self.rivalry),
        ]
        lines = ["## Porter 5 Forces", "", "| Force | Severity | Rationale |",
                 "|---|---|---|"]
        emoji = {"low": "🟢", "med": "🟡", "high": "🔴"}
        for name, force in forces:
            lines.append(
                f"| {name} | {emoji[force.severity]} {force.severity} | {force.rationale} |"
            )
        if self.summary:
            lines += ["", f"**Net Assessment:** {self.summary}"]
        return "\n".join(lines)
