"""Frameworks Library (C25) — MBB-급 컨설팅 frameworks 모음.

각 framework는 stdlib-only. council 페르소나가 채울 schema + markdown render.
council-runner의 layer별 prompt에 자동 주입돼 페르소나가 정형 출력하도록 강제.

Frameworks:
- Porter 5 Forces (L2 competitor landscape)
- JTBD (L3 customer)
- SWOT (L9 counterargs)
- North Star Tree (L8 KPI)
- MECE Tree (L1 sizing, L8 KPI)
"""

from __future__ import annotations

from .porter import Porter5Forces, ForceLevel
from .jtbd import JTBD, JobDimension
from .swot import SWOT
from .north_star_tree import NorthStarTree, KPIDriver
from .mece_tree import MECETree, MECENode
from .registry import frameworks_for_layer, framework_prompt_block

__all__ = [
    "Porter5Forces", "ForceLevel",
    "JTBD", "JobDimension",
    "SWOT",
    "NorthStarTree", "KPIDriver",
    "MECETree", "MECENode",
    "frameworks_for_layer",
    "framework_prompt_block",
]
