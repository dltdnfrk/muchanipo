#!/usr/bin/env python3
"""MAP-Elites 기반 진화 실행 보조 도구.

외부 의존성 없이 후보의 품질(performance)과 행동 특성(behavior)을
격자 셀로 나누어 다양성을 보존한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Sequence, Tuple, Union

try:
    from src.safety.lockdown import validate_evolve_proposal
except Exception:  # pragma: no cover - 독립 실행 환경 fallback
    def validate_evolve_proposal(proposal: Mapping[str, Any] | None) -> Tuple[bool, List[str]]:
        if not isinstance(proposal, Mapping):
            return False, ["proposal must be a mapping"]
        immutable = {"citation_fidelity", "reliability"}
        errors: List[str] = []
        for change in proposal.get("changes", []):
            if isinstance(change, Mapping) and change.get("axis") in immutable:
                errors.append(f"immutable axis cannot evolve: {change.get('axis')}")
        return not errors, errors


Number = Union[int, float]
CellKey = Tuple[Tuple[str, int], ...]


@dataclass(frozen=True)
class Elite:
    """아카이브 셀의 최고 후보."""

    candidate: Mapping[str, Any]
    performance: float
    behavior: Mapping[str, float]
    cell: CellKey


class MAPElitesArchive:
    """행동 차원별 grid에서 셀마다 최고 성능 후보만 유지한다."""

    def __init__(
        self,
        behavior_dims: Sequence[str],
        bins: int = 10,
        ranges: Mapping[str, Tuple[float, float]] | None = None,
    ) -> None:
        if not behavior_dims:
            raise ValueError("behavior_dims must not be empty")
        if bins < 1:
            raise ValueError("bins must be >= 1")
        self.behavior_dims = tuple(str(dim) for dim in behavior_dims)
        self.bins = int(bins)
        self.ranges = dict(ranges or {})
        self._cells: MutableMapping[CellKey, Elite] = {}

    def add(
        self,
        candidate: Mapping[str, Any],
        performance: Number,
        behavior: Mapping[str, Number],
    ) -> bool:
        """후보를 추가하고 셀 elite가 갱신되면 True를 반환한다."""
        if not isinstance(candidate, Mapping):
            raise TypeError("candidate must be a mapping")
        score = float(performance)
        if not 0.0 <= score <= 1.0:
            raise ValueError("performance must be between 0.0 and 1.0")

        proposal = candidate.get("proposal")
        if proposal is None:
            proposal = candidate
        ok, errors = validate_evolve_proposal(proposal)
        if not ok:
            raise ValueError("unsafe evolve proposal: " + "; ".join(errors))

        cell = self._cell_for(behavior)
        normalized_behavior = {dim: float(behavior[dim]) for dim in self.behavior_dims}
        current = self._cells.get(cell)
        if current is not None and current.performance >= score:
            return False

        self._cells[cell] = Elite(
            candidate=dict(candidate),
            performance=score,
            behavior=normalized_behavior,
            cell=cell,
        )
        return True

    def get_elites(self) -> List[Elite]:
        """성능 내림차순으로 elite 목록을 반환한다."""
        return sorted(self._cells.values(), key=lambda elite: elite.performance, reverse=True)

    def coverage(self) -> float:
        """현재 점유된 셀 비율."""
        total = self.bins ** len(self.behavior_dims)
        return round(len(self._cells) / total, 6)

    def _cell_for(self, behavior: Mapping[str, Number]) -> CellKey:
        missing = [dim for dim in self.behavior_dims if dim not in behavior]
        if missing:
            raise ValueError("behavior missing dims: " + ", ".join(missing))
        return tuple((dim, self._bin(dim, float(behavior[dim]))) for dim in self.behavior_dims)

    def _bin(self, dim: str, value: float) -> int:
        low, high = self.ranges.get(dim, (0.0, 1.0))
        if high <= low:
            raise ValueError(f"invalid range for {dim}")
        clipped = min(max(value, low), high)
        if clipped == high:
            return self.bins - 1
        width = (high - low) / self.bins
        return int((clipped - low) / width)


class SEWOptimizer:
    """SEW 방식의 품질/다양성 가중 후보 선택기.

    quality_weight와 diversity_weight를 조정해 기존 elite와 다른 행동을
    가진 후보를 우대할 수 있다.
    """

    def __init__(self, quality_weight: float = 0.7, diversity_weight: float = 0.3) -> None:
        if quality_weight < 0 or diversity_weight < 0:
            raise ValueError("weights must be non-negative")
        total = quality_weight + diversity_weight
        if total == 0:
            raise ValueError("at least one weight must be positive")
        self.quality_weight = quality_weight / total
        self.diversity_weight = diversity_weight / total

    def rank(
        self,
        candidates: Iterable[Mapping[str, Any]],
        archive: MAPElitesArchive,
    ) -> List[Dict[str, Any]]:
        """후보를 SEW 점수 내림차순으로 정렬해 반환한다."""
        elites = archive.get_elites()
        ranked: List[Dict[str, Any]] = []
        for candidate in candidates:
            performance = float(candidate.get("performance", 0.0))
            behavior = candidate.get("behavior", {})
            if not isinstance(behavior, Mapping):
                raise ValueError("candidate behavior must be a mapping")
            diversity = self._diversity_score(behavior, elites)
            score = (self.quality_weight * performance) + (self.diversity_weight * diversity)
            ranked.append(
                {
                    "candidate": candidate,
                    "score": round(score, 6),
                    "quality": performance,
                    "diversity": round(diversity, 6),
                }
            )
        return sorted(ranked, key=lambda item: item["score"], reverse=True)

    def select(
        self,
        candidates: Iterable[Mapping[str, Any]],
        archive: MAPElitesArchive,
        limit: int = 1,
    ) -> List[Mapping[str, Any]]:
        """상위 limit개 원본 후보를 반환한다."""
        if limit < 1:
            raise ValueError("limit must be >= 1")
        return [item["candidate"] for item in self.rank(candidates, archive)[:limit]]

    def _diversity_score(self, behavior: Mapping[str, Any], elites: Sequence[Elite]) -> float:
        if not elites:
            return 1.0
        distances = []
        for elite in elites:
            per_dim = []
            for dim, value in behavior.items():
                if dim in elite.behavior and isinstance(value, (int, float)):
                    per_dim.append(abs(float(value) - elite.behavior[dim]))
            if per_dim:
                distances.append(sum(per_dim) / len(per_dim))
        if not distances:
            return 1.0
        return min(1.0, max(0.0, min(distances)))
