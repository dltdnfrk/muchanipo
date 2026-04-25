"""North Star Tree — L8 KPI tree framework (Sean Ellis / Reforge)."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class KPIDriver:
    """KPI driver — 북극성 산출에 기여하는 leading 지표."""
    name: str
    current_value: str = ""
    target_value: str = ""
    cadence: str = "monthly"  # daily/weekly/monthly/quarterly
    owner: str = ""


@dataclass
class NorthStarTree:
    """북극성 KPI + driver 트리."""
    north_star_metric: str
    north_star_definition: str
    current_value: str = ""
    target_value: str = ""
    drivers: List[KPIDriver] = field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [f"## North Star Tree — {self.north_star_metric}", "",
                 f"**정의:** {self.north_star_definition}", ""]
        if self.current_value or self.target_value:
            lines += [f"**현재:** {self.current_value}  →  **목표:** {self.target_value}", ""]
        if self.drivers:
            lines += ["### Driver Metrics", "",
                      "| Driver | 현재 | 목표 | Cadence | Owner |",
                      "|---|---|---|---|---|"]
            for d in self.drivers:
                lines.append(
                    f"| {d.name} | {d.current_value} | {d.target_value} | "
                    f"{d.cadence} | {d.owner} |"
                )
        return "\n".join(lines).rstrip()
