"""EvoAgentX MAP-Elites 다양성 매퍼.

Council 페르소나 풀에서 관점 중복을 차단하기 위한 2D 다양성 맵.

축:
    - risk_tolerance         (0.0 ~ 1.0)
    - innovation_orientation (0.0 ~ 1.0)

각 축을 ``bins_per_axis`` 개 셀로 양자화해 (i, j) 좌표를 부여한다.
한 셀에는 최고 fitness 페르소나 1명만 점유 — 새 후보가 오면
fitness 비교로 교체 여부 결정.

stdlib only. PRD-v2 §5.5 (EvoAgentX MAP-Elites) 참조.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Set, Tuple


Coord = Tuple[int, int]


@dataclass(frozen=True)
class MapCell:
    """다양성 맵의 한 셀."""

    coord: Coord
    persona_id: str
    fitness: float
    risk_tolerance: float
    innovation_orientation: float


@dataclass
class DiversityMap:
    """2D 다양성 맵 — risk_tolerance × innovation_orientation."""

    bins_per_axis: int = 4
    cells: Dict[Coord, MapCell] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.bins_per_axis < 2:
            raise ValueError("bins_per_axis must be >= 2")

    @property
    def total_cells(self) -> int:
        return self.bins_per_axis * self.bins_per_axis

    def _bucket(self, value: float) -> int:
        """0..1 값을 0..bins-1 정수 버킷으로 양자화."""
        if value < 0.0:
            value = 0.0
        elif value > 1.0:
            value = 1.0
        idx = int(value * self.bins_per_axis)
        if idx >= self.bins_per_axis:
            idx = self.bins_per_axis - 1
        return idx

    def coord_for(self, value_axes: Mapping[str, Any]) -> Coord:
        """value_axes로부터 (i, j) 셀 좌표 계산."""
        risk = _as_float(value_axes.get("risk_tolerance"), default=0.5)
        innov = _as_float(value_axes.get("innovation_orientation"), default=0.5)
        return (self._bucket(risk), self._bucket(innov))

    def admit(
        self,
        persona_id: str,
        value_axes: Mapping[str, Any],
        fitness: float = 1.0,
    ) -> bool:
        """페르소나를 맵에 등록 시도.

        Returns:
            True  — 새로 등록되었거나 기존 셀을 교체함
            False — 같은 셀에 더 높은 fitness 점유자가 있어 거부됨
        """
        risk = _as_float(value_axes.get("risk_tolerance"), default=0.5)
        innov = _as_float(value_axes.get("innovation_orientation"), default=0.5)
        coord = (self._bucket(risk), self._bucket(innov))

        existing = self.cells.get(coord)
        if existing is not None and existing.fitness >= fitness:
            return False

        self.cells[coord] = MapCell(
            coord=coord,
            persona_id=persona_id,
            fitness=float(fitness),
            risk_tolerance=risk,
            innovation_orientation=innov,
        )
        return True

    def is_occupied(self, value_axes: Mapping[str, Any]) -> bool:
        return self.coord_for(value_axes) in self.cells

    def occupied_coords(self) -> Set[Coord]:
        return set(self.cells.keys())

    def coverage(self) -> float:
        """0.0~1.0 — 점유된 셀 비율."""
        return len(self.cells) / self.total_cells

    def free_coords(self) -> Set[Coord]:
        all_coords = {
            (i, j)
            for i in range(self.bins_per_axis)
            for j in range(self.bins_per_axis)
        }
        return all_coords - self.occupied_coords()

    def suggest_redirect(self) -> Optional[Mapping[str, float]]:
        """비어있는 셀 중심 좌표를 value_axes 형태로 추천.

        propose 단계에서 다양성 강제할 때 사용.
        """
        free = self.free_coords()
        if not free:
            return None
        # 결정성 확보: 정렬된 첫 셀의 중심 사용
        i, j = sorted(free)[0]
        center = lambda idx: (idx + 0.5) / self.bins_per_axis  # noqa: E731
        return {
            "risk_tolerance": center(i),
            "innovation_orientation": center(j),
        }

    def to_dict(self) -> Dict[str, Any]:
        """직렬화용 dict (JSON 호환)."""
        return {
            "bins_per_axis": self.bins_per_axis,
            "coverage": self.coverage(),
            "cells": [
                {
                    "coord": list(cell.coord),
                    "persona_id": cell.persona_id,
                    "fitness": cell.fitness,
                    "risk_tolerance": cell.risk_tolerance,
                    "innovation_orientation": cell.innovation_orientation,
                }
                for cell in self.cells.values()
            ],
        }


def _as_float(value: Any, default: float = 0.5) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
