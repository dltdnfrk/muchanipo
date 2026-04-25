#!/usr/bin/env python3
"""Council persona value-axis helpers.

SCOPE 계열 결과를 반영해 인구통계 속성보다 의사결정 성향을 직접 표현하는
4축 값을 다룬다. 외부 schema 파일 통합은 상위 통합 단계에서 수행한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


TIME_HORIZONS = frozenset({"short", "mid", "long"})
STAKEHOLDER_PRIORITIES = frozenset({"primary", "secondary", "tertiary"})


AGENT_MANIFEST_VALUE_AXES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "time_horizon",
        "risk_tolerance",
        "stakeholder_priority",
        "innovation_orientation",
    ],
    "properties": {
        "time_horizon": {"type": "string", "enum": sorted(TIME_HORIZONS)},
        "risk_tolerance": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "stakeholder_priority": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "enum": sorted(STAKEHOLDER_PRIORITIES)},
        },
        "innovation_orientation": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
}


@dataclass(frozen=True)
class ValueAxes:
    """Persona 관점 bias를 만드는 4축 값 컨테이너."""

    time_horizon: str
    risk_tolerance: float
    stakeholder_priority: tuple[str, ...]
    innovation_orientation: float

    def __init__(
        self,
        time_horizon: str,
        risk_tolerance: float,
        stakeholder_priority: Sequence[str],
        innovation_orientation: float,
    ) -> None:
        object.__setattr__(self, "time_horizon", time_horizon)
        object.__setattr__(self, "risk_tolerance", float(risk_tolerance))
        object.__setattr__(self, "stakeholder_priority", tuple(stakeholder_priority))
        object.__setattr__(self, "innovation_orientation", float(innovation_orientation))

        errors = validate_value_axes(self.to_manifest_fragment())
        if errors:
            raise ValueError("; ".join(errors))

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "ValueAxes":
        """Manifest dict에서 value_axes 값을 만든다."""
        return cls(
            time_horizon=str(raw.get("time_horizon", "")),
            risk_tolerance=_required_number(raw, "risk_tolerance"),
            stakeholder_priority=_required_sequence(raw, "stakeholder_priority"),
            innovation_orientation=_required_number(raw, "innovation_orientation"),
        )

    @classmethod
    def schema_property(cls) -> dict[str, Any]:
        """agent-manifest.schema.json에 병합 가능한 property fragment."""
        return dict(AGENT_MANIFEST_VALUE_AXES_SCHEMA)

    def to_manifest_fragment(self) -> dict[str, Any]:
        """JSON manifest에 그대로 넣을 수 있는 stdlib dict로 변환한다."""
        return {
            "time_horizon": self.time_horizon,
            "risk_tolerance": self.risk_tolerance,
            "stakeholder_priority": list(self.stakeholder_priority),
            "innovation_orientation": self.innovation_orientation,
        }

    def to_perspective_bias(self) -> str:
        """Council prompt에 넣을 자연어 관점 bias 조각을 만든다."""
        time_text = {
            "short": "단기 실행성과 빠른 피드백",
            "mid": "중기 학습과 운영 안정성",
            "long": "장기 복리 효과와 제도적 지속성",
        }[self.time_horizon]
        risk_text = _band(
            self.risk_tolerance,
            low="위험 회피적으로 검증된 선택을 선호",
            mid="위험과 기회 비용을 균형 있게 비교",
            high="높은 불확실성도 상방 가능성이 크면 수용",
        )
        innovation_text = _band(
            self.innovation_orientation,
            low="기존 운영 방식과 호환성을 우선",
            mid="검증된 신기술을 점진적으로 도입",
            high="차별적 혁신성과 새 접근법을 적극 탐색",
        )
        stakeholder_text = " > ".join(_stakeholder_label(item) for item in self.stakeholder_priority)
        return (
            f"관점 bias: {time_text}을 우선한다. {risk_text}. "
            f"이해관계자 우선순위는 {stakeholder_text} 순서다. {innovation_text}."
        )


def validate_value_axes(raw: Mapping[str, Any] | None) -> list[str]:
    """value_axes payload를 dependency 없이 검증한다."""
    if not isinstance(raw, Mapping):
        return ["value_axes must be an object"]

    errors: list[str] = []
    time_horizon = raw.get("time_horizon")
    if time_horizon not in TIME_HORIZONS:
        errors.append("value_axes.time_horizon must be one of short, mid, long")

    _validate_number(raw.get("risk_tolerance"), "value_axes.risk_tolerance", errors)
    _validate_number(raw.get("innovation_orientation"), "value_axes.innovation_orientation", errors)

    priority = raw.get("stakeholder_priority")
    if not isinstance(priority, list) or not priority:
        errors.append("value_axes.stakeholder_priority must be a non-empty list")
    else:
        for idx, item in enumerate(priority):
            if item not in STAKEHOLDER_PRIORITIES:
                errors.append(
                    f"value_axes.stakeholder_priority[{idx}] must be one of primary, secondary, tertiary"
                )
    return errors


def _required_number(raw: Mapping[str, Any], key: str) -> float:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"value_axes.{key} must be a number")
    return float(value)


def _required_sequence(raw: Mapping[str, Any], key: str) -> list[str]:
    value = raw.get(key)
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"value_axes.{key} must be a sequence")
    return [str(item) for item in value]


def _validate_number(value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(f"{path} must be a number")
        return
    if not 0.0 <= float(value) <= 1.0:
        errors.append(f"{path} must be between 0.0 and 1.0")


def _band(value: float, *, low: str, mid: str, high: str) -> str:
    if value < 0.34:
        return low
    if value < 0.67:
        return mid
    return high


def _stakeholder_label(value: str) -> str:
    return {
        "primary": "1차 사용자/고객",
        "secondary": "운영자/파트너",
        "tertiary": "사회/규제/장기 생태계",
    }[value]
