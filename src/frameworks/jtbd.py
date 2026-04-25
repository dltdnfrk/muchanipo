"""Jobs-To-Be-Done (Christensen) — L3 customer JTBD framework."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List


@dataclass
class JobDimension:
    """JTBD 1축 (functional/emotional/social)."""
    dimension: str  # "functional" | "emotional" | "social"
    job: str        # 고객이 hire한 job
    current_solution: str  # 현재 hire한 솔루션
    underperformance_gap: str  # 그 솔루션의 부족한 점

    def __post_init__(self):
        if self.dimension not in {"functional", "emotional", "social"}:
            raise ValueError(f"dimension must be functional/emotional/social, got {self.dimension}")


@dataclass
class JTBD:
    """3축 JTBD — Functional + Emotional + Social."""
    target_customer: str
    functional: JobDimension
    emotional: JobDimension
    social: JobDimension

    fire_candidates: List[str] = field(default_factory=list)
    hire_candidates: List[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [f"## Jobs-To-Be-Done — {self.target_customer}", "",
                 "| 차원 | Job | 현재 솔루션 | Underperformance Gap |",
                 "|---|---|---|---|"]
        for jd in (self.functional, self.emotional, self.social):
            lines.append(
                f"| {jd.dimension} | {jd.job} | {jd.current_solution} | "
                f"{jd.underperformance_gap} |"
            )
        if self.fire_candidates:
            lines += ["", "**Fire 후보 (현재 솔루션에서 교체):**"]
            lines += [f"- {f}" for f in self.fire_candidates]
        if self.hire_candidates:
            lines += ["", "**Hire 후보 (새로 채용 가능):**"]
            lines += [f"- {h}" for h in self.hire_candidates]
        return "\n".join(lines)
