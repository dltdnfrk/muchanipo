#!/usr/bin/env python3
"""HACHIMI 스타일 페르소나 생성 파이프라인.

외부 LLM 호출 없이 Propose -> Validate -> Revise 단계를 재현한다.
온톨로지는 단순 mapping으로 받아 테스트와 야간 자동화에서 안전하게 쓸 수
있도록 stdlib만 사용한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

try:  # 안전 모듈이 없는 독립 실행 환경에서도 fail-closed 검증 결과를 제공한다.
    from src.safety.lockdown import aup_risk, validate_persona_manifest
except Exception:  # pragma: no cover - repo 외부 재사용 fallback
    aup_risk = None  # type: ignore[assignment]
    validate_persona_manifest = None  # type: ignore[assignment]


DEFAULT_VALUE_AXES: Dict[str, Any] = {
    "time_horizon": "mid",
    "risk_tolerance": 0.35,
    "stakeholder_priority": ["primary", "secondary", "tertiary"],
    "innovation_orientation": 0.55,
}


@dataclass(frozen=True)
class Draft:
    """propose 단계의 검증 전 후보."""

    persona_id: str
    name: str
    role: str
    intent: str
    allowed_tools: List[str]
    required_outputs: List[str]
    value_axes: Dict[str, Any] = field(default_factory=dict)
    manifest: Dict[str, Any] = field(default_factory=dict)

    def to_manifest(self) -> Dict[str, Any]:
        manifest = {
            "intent": self.intent,
            "allowed_tools": list(self.allowed_tools),
            "required_outputs": list(self.required_outputs),
            "role": self.role,
            "value_axes": dict(self.value_axes),
        }
        manifest.update(self.manifest)
        return manifest


@dataclass(frozen=True)
class ValidationIssue:
    """validate 단계에서 발견한 후보별 문제."""

    persona_id: str
    code: str
    message: str


@dataclass(frozen=True)
class ValidationReport:
    """검증 결과와 후보별 통과 여부."""

    valid_ids: List[str]
    issues: List[ValidationIssue]

    @property
    def ok(self) -> bool:
        return not self.issues

    def issues_for(self, persona_id: str) -> List[ValidationIssue]:
        return [issue for issue in self.issues if issue.persona_id == persona_id]


@dataclass(frozen=True)
class FinalPersona:
    """revise 단계 이후 자동화에 넘길 수 있는 최종 페르소나."""

    persona_id: str
    name: str
    role: str
    manifest: Dict[str, Any]
    revision_notes: List[str] = field(default_factory=list)


class PersonaGenerator:
    """HACHIMI 3단계 페르소나 생성기.

    ontology 예시 키:
    - roles: 허용 역할 목록
    - intents: 역할별/순서별 intent 후보
    - allowed_tools: 허용 도구 목록
    - required_outputs: 필수 산출물 목록
    - value_axes: C16 축이 들어오면 그대로 사용
    - denied_terms / high_risk_terms: 안전 차단 용어
    """

    def __init__(self, risk_threshold: float = 0.45) -> None:
        self.risk_threshold = float(risk_threshold)

    def propose(
        self,
        ontology: Mapping[str, Any],
        target_count: int,
        seed_personas: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> List[Draft]:
        """Draft를 target_count만큼 생성.

        seed_personas가 제공되면 (예: KoreaPersonaSampler.agtech_farmer_seed 결과)
        각 Draft의 name·manifest에 grounded 인구통계 정보를 주입한다. propose 단계
        자체는 stdlib only — 검증/수정은 후속 validate/revise에서.
        """
        if target_count < 1:
            return []

        roles = _string_list(ontology.get("roles")) or ["evidence_reviewer"]
        intents = _string_list(ontology.get("intents")) or [
            "Summarize grounded evidence and report uncertainty."
        ]
        allowed_tools = _string_list(ontology.get("allowed_tools")) or ["read_file"]
        required_outputs = _string_list(ontology.get("required_outputs")) or ["report"]
        base_axes = _value_axes(ontology.get("value_axes"))
        seeds = list(seed_personas) if seed_personas else []

        drafts: List[Draft] = []
        for index in range(target_count):
            role = roles[index % len(roles)]
            intent = intents[index % len(intents)]
            persona_id = f"persona-{index + 1:03d}"
            seed = seeds[index] if index < len(seeds) else None

            if seed:
                # grounded 이름: "농업 종사자 1" 대신 "{province} {city} {occupation}"
                province = str(seed.get("province") or "").strip()
                city = str(seed.get("city") or seed.get("sigungu") or "").strip()
                occupation = str(seed.get("occupation") or role).strip()
                grounded_name = " ".join(
                    p for p in (province, city, occupation) if p
                ) or f"{role.replace('_', ' ').title()} {index + 1}"
                manifest_extra: Dict[str, Any] = {
                    "grounded_seed": {
                        "persona_id": seed.get("persona_id", ""),
                        "province": province,
                        "city": city,
                        "age": seed.get("age", ""),
                        "gender": seed.get("gender", ""),
                        "occupation": occupation,
                        "persona_text": seed.get("persona", ""),
                        "source": seed.get("source", "Nemotron-Personas-Korea"),
                    }
                }
            else:
                grounded_name = f"{role.replace('_', ' ').title()} {index + 1}"
                manifest_extra = {}

            drafts.append(
                Draft(
                    persona_id=persona_id,
                    name=grounded_name,
                    role=role,
                    intent=intent,
                    allowed_tools=allowed_tools,
                    required_outputs=required_outputs,
                    value_axes=dict(base_axes),
                    manifest=manifest_extra,
                )
            )
        return drafts

    def validate(
        self,
        drafts: Sequence[Draft],
        ontology: Mapping[str, Any],
        value_axes_required: bool = True,
    ) -> ValidationReport:
        issues: List[ValidationIssue] = []
        valid_ids: List[str] = []
        allowed_roles = set(_string_list(ontology.get("roles")))
        allowed_tools = set(_string_list(ontology.get("allowed_tools")))
        required_outputs = set(_string_list(ontology.get("required_outputs")))
        denied_terms = _string_list(ontology.get("denied_terms")) + _string_list(
            ontology.get("high_risk_terms")
        )

        for draft in drafts:
            draft_issues = self._validate_one(
                draft,
                ontology,
                allowed_roles,
                allowed_tools,
                required_outputs,
                denied_terms,
                value_axes_required,
            )
            if draft_issues:
                issues.extend(draft_issues)
            else:
                valid_ids.append(draft.persona_id)
        return ValidationReport(valid_ids=valid_ids, issues=issues)

    def revise(
        self,
        drafts: Sequence[Draft],
        validation: ValidationReport,
    ) -> List[FinalPersona]:
        valid = set(validation.valid_ids)
        finals: List[FinalPersona] = []
        for draft in drafts:
            if draft.persona_id not in valid:
                continue
            manifest = draft.to_manifest()
            manifest.setdefault("value_axes", dict(DEFAULT_VALUE_AXES))
            finals.append(
                FinalPersona(
                    persona_id=draft.persona_id,
                    name=draft.name,
                    role=draft.role,
                    manifest=manifest,
                    revision_notes=["validated_against_ontology", "lockdown_checked"],
                )
            )
        return finals

    def _validate_one(
        self,
        draft: Draft,
        ontology: Mapping[str, Any],
        allowed_roles: set[str],
        allowed_tools: set[str],
        required_outputs: set[str],
        denied_terms: Sequence[str],
        value_axes_required: bool,
    ) -> List[ValidationIssue]:
        issues: List[ValidationIssue] = []
        manifest = draft.to_manifest()

        if allowed_roles and draft.role not in allowed_roles:
            issues.append(_issue(draft, "ontology.role", f"role not allowed: {draft.role}"))

        unknown_tools = sorted(set(draft.allowed_tools) - allowed_tools) if allowed_tools else []
        if unknown_tools:
            issues.append(_issue(draft, "ontology.tools", f"unknown tools: {unknown_tools}"))

        missing_outputs = sorted(required_outputs - set(draft.required_outputs))
        if missing_outputs:
            issues.append(
                _issue(draft, "ontology.outputs", f"missing outputs: {missing_outputs}")
            )

        if value_axes_required:
            axis_errors = _validate_value_axes(manifest.get("value_axes"))
            issues.extend(_issue(draft, "value_axes", error) for error in axis_errors)

        lowered = _manifest_text(manifest).lower()
        for term in denied_terms:
            if term and str(term).lower() in lowered:
                issues.append(_issue(draft, "aup.denied_term", f"denied term present: {term}"))

        if aup_risk is not None:
            risk = float(aup_risk(_manifest_text(manifest), ontology))
            if risk >= self.risk_threshold:
                issues.append(_issue(draft, "aup.risk", f"risk score {risk} >= threshold"))

        if validate_persona_manifest is not None:
            ok, errors = validate_persona_manifest(manifest)
            if not ok:
                issues.extend(_issue(draft, "lockdown", error) for error in errors)

        return issues


def _string_list(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, Iterable):
        return [str(item) for item in value if str(item)]
    return []


def _value_axes(value: Any) -> Dict[str, Any]:
    if isinstance(value, Mapping):
        axes = dict(DEFAULT_VALUE_AXES)
        axes.update(value)
        return axes
    return dict(DEFAULT_VALUE_AXES)


def _validate_value_axes(value: Any) -> List[str]:
    if not isinstance(value, Mapping):
        return ["value_axes must be a mapping"]

    errors: List[str] = []
    if value.get("time_horizon") not in {"short", "mid", "long"}:
        errors.append("time_horizon must be short, mid, or long")
    for key in ("risk_tolerance", "innovation_orientation"):
        try:
            numeric = float(value.get(key))
        except (TypeError, ValueError):
            errors.append(f"{key} must be numeric")
            continue
        if numeric < 0.0 or numeric > 1.0:
            errors.append(f"{key} must be between 0.0 and 1.0")
    priorities = value.get("stakeholder_priority")
    if not isinstance(priorities, Sequence) or isinstance(priorities, (str, bytes)):
        errors.append("stakeholder_priority must be a list")
    elif not all(str(item) for item in priorities):
        errors.append("stakeholder_priority must not contain blank values")
    return errors


def _manifest_text(manifest: Mapping[str, Any]) -> str:
    return " ".join(str(value) for value in manifest.values())


def _issue(draft: Draft, code: str, message: str) -> ValidationIssue:
    return ValidationIssue(persona_id=draft.persona_id, code=code, message=message)
