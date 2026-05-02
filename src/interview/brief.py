"""ResearchBrief contract produced by the PRD-style interview."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:
    from src.targeting import TargetingMap
except Exception:  # pragma: no cover
    TargetingMap = None  # type: ignore[misc,assignment]


@dataclass
class ResearchBrief:
    raw_idea: str
    research_question: str
    purpose: str
    context: str = ""
    known_facts: list[str] = field(default_factory=list)
    deliverable_type: str = "report"
    quality_bar: str = "evidence-backed"
    constraints: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    coverage_score: float = 0.0
    targeting_map: "TargetingMap | None" = None
    planning_prd: dict[str, Any] = field(default_factory=dict)
    feature_hierarchy: list[dict[str, Any]] = field(default_factory=list)
    user_flow: dict[str, Any] = field(default_factory=dict)
    planning_review_policy: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        seed = self.research_question or self.raw_idea or "brief"
        return "brief-" + str(abs(hash(seed)) % 10_000_000)

    @property
    def is_ready(self) -> bool:
        return bool(
            self.research_question.strip()
            and self.purpose.strip()
            and self.coverage_score >= 0.75
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict; targeting_map is nested if present."""
        data: dict[str, Any] = {
            "raw_idea": self.raw_idea,
            "research_question": self.research_question,
            "purpose": self.purpose,
            "context": self.context,
            "known_facts": self.known_facts,
            "deliverable_type": self.deliverable_type,
            "quality_bar": self.quality_bar,
            "constraints": self.constraints,
            "success_criteria": self.success_criteria,
            "coverage_score": self.coverage_score,
            "is_ready": self.is_ready,
            "planning_prd": self.planning_prd,
            "feature_hierarchy": self.feature_hierarchy,
            "user_flow": self.user_flow,
            "planning_review_policy": self.planning_review_policy,
        }
        if self.targeting_map is not None:
            data["targeting_map"] = self.targeting_map.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResearchBrief":
        """Deserialize from a plain dict; tolerant of missing keys."""
        tmap_data = data.get("targeting_map")
        tmap = None
        if tmap_data is not None and TargetingMap is not None:
            try:
                tmap = TargetingMap.from_dict(tmap_data)
            except Exception:
                pass
        return cls(
            raw_idea=data.get("raw_idea", ""),
            research_question=data.get("research_question", ""),
            purpose=data.get("purpose", ""),
            context=data.get("context", ""),
            known_facts=_list_or_empty(data.get("known_facts")),
            deliverable_type=data.get("deliverable_type", "report"),
            quality_bar=data.get("quality_bar", "evidence-backed"),
            constraints=_list_or_empty(data.get("constraints")),
            success_criteria=_list_or_empty(data.get("success_criteria")),
            coverage_score=float(data.get("coverage_score", 0.0)),
            targeting_map=tmap,
            planning_prd=_dict_or_empty(data.get("planning_prd")),
            feature_hierarchy=_list_or_empty(data.get("feature_hierarchy")),
            user_flow=_dict_or_empty(data.get("user_flow")),
            planning_review_policy=_dict_or_empty(data.get("planning_review_policy")),
        )


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_or_empty(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []
