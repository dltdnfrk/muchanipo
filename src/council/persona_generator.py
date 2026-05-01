#!/usr/bin/env python3
"""HACHIMI 스타일 페르소나 생성 파이프라인.

기본값은 외부 LLM 호출 없이 Propose -> Validate -> Revise 단계를 재현한다.
GatewayV2가 주입되면 Stage 1 propose와 Stage 2 deep validate에 LLM 모드를
추가로 사용하고, 실패 시 기존 휴리스틱 경로로 폴백한다.

PRD-v2 §5.2 Neuro-Symbolic Validator 추가:
    - Fast Validator (규칙 기반, 즉시 실행) — ontology / denied_terms /
      value_axes / lockdown / AUP risk
    - Deep Validator — 기본 키워드 오버랩 + 선택적 LLM judge +
      한국어 실명 타겟팅 추가 차단

PRD-v2 §5.5 EvoAgentX MAP-Elites 통합:
    - generate() 메서드가 DiversityMap을 받아 Final 단계에서 셀 점유 강제
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:  # 안전 모듈이 없는 독립 실행 환경에서도 fail-closed 검증 결과를 제공한다.
    from src.safety.lockdown import aup_risk, validate_persona_manifest
except Exception:  # pragma: no cover - repo 외부 재사용 fallback
    aup_risk = None  # type: ignore[assignment]
    validate_persona_manifest = None  # type: ignore[assignment]

try:
    from src.council.diversity_mapper import DiversityMap
except Exception:  # pragma: no cover - 순환 import 회피
    DiversityMap = None  # type: ignore[assignment]

from src.council.persona_prompts import (
    build_persona_deep_validate_prompt,
    build_persona_propose_prompt,
    parse_persona_proposal_response,
    parse_persona_validation_response,
)
from src.execution.gateway_v2 import GatewayV2
from src.runtime.live_mode import LiveModeViolation


# ---- Korean real-name targeting guard --------------------------------------
# 한국어 실명 + 직책 패턴만 위험 신호로 판단한다. 일반 역할명
# ("사용자대표")이나 UX 문구("고객 인터뷰")는 과탐지하지 않는다.
_COMMON_KOREAN_SURNAMES = (
    "김이박최정강조윤장임한오서신권황안송류홍전고문양손배백허"
    "유남심노하곽성차주우구민진지엄채원천방공현함변염여추"
    "도소석선설마길"
)
_KOREAN_NAME_RX = re.compile(
    rf"(?:^|[\s:=\"'(\[])[{_COMMON_KOREAN_SURNAMES}][가-힣]{{1,3}}\s*"
    r"(?:대표|회장|사장|이사|장관|총장|교수)(?=$|[\s,.;:)\]\"'])"
)
_KOREAN_DOXX_TOKENS = ("주민등록", "거주지", "주소", "휴대폰번호", "전화번호")


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

    def __init__(
        self,
        gateway: GatewayV2 | None = None,
        risk_threshold: float = 0.45,
    ) -> None:
        if isinstance(gateway, (int, float)) and risk_threshold == 0.45:
            risk_threshold = float(gateway)
            gateway = None
        self.gateway = gateway
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

            value_axes = _value_axes_for_index(base_axes, index, target_count)
            drafts.append(
                Draft(
                    persona_id=persona_id,
                    name=grounded_name,
                    role=role,
                    intent=intent,
                    allowed_tools=allowed_tools,
                    required_outputs=required_outputs,
                    value_axes=value_axes,
                    manifest=manifest_extra,
                )
            )
        return drafts

    def propose_with_llm(
        self,
        ontology: Mapping[str, Any],
        target_count: int,
        topic: str,
    ) -> List[Draft]:
        """Use GatewayV2 to propose Drafts, falling back to heuristic propose on failure."""

        if target_count < 1:
            return []
        if self.gateway is None:
            return self.propose(ontology, target_count=target_count)

        prompt = build_persona_propose_prompt(ontology, target_count, topic)
        try:
            result = self.gateway.call("council", prompt)
            raw_personas = parse_persona_proposal_response(result.text)
            drafts = self._drafts_from_llm_specs(raw_personas, ontology, target_count)
        except LiveModeViolation:
            raise
        except Exception:
            return self.propose(ontology, target_count=target_count)
        if len(drafts) < target_count:
            fallback = self.propose(ontology, target_count=target_count)
            used_ids = {draft.persona_id for draft in drafts}
            for draft in fallback:
                if len(drafts) >= target_count:
                    break
                if draft.persona_id not in used_ids:
                    drafts.append(draft)
        return drafts[:target_count]

    def _drafts_from_llm_specs(
        self,
        specs: Sequence[Mapping[str, Any]],
        ontology: Mapping[str, Any],
        target_count: int,
    ) -> List[Draft]:
        roles = _string_list(ontology.get("roles")) or ["evidence_reviewer"]
        allowed_tools_default = _string_list(ontology.get("allowed_tools")) or ["read_file"]
        outputs_default = _string_list(ontology.get("required_outputs")) or ["report"]
        axes_default = _value_axes(ontology.get("value_axes"))

        drafts: List[Draft] = []
        for index, spec in enumerate(specs[:target_count]):
            role = _clean_text(spec.get("role")) or roles[index % len(roles)]
            intent = (
                _clean_text(spec.get("intent"))
                or _clean_text(spec.get("purpose"))
                or "Summarize grounded evidence and report uncertainty."
            )
            persona_id = _clean_text(spec.get("persona_id")) or f"persona-{index + 1:03d}"
            name = _clean_text(spec.get("name")) or f"{role.replace('_', ' ').title()} {index + 1}"
            allowed_tools = _string_list(spec.get("allowed_tools")) or allowed_tools_default
            required_outputs = _string_list(spec.get("required_outputs")) or outputs_default
            value_axes = _value_axes(spec.get("value_axes") or axes_default)
            manifest = spec.get("manifest")
            manifest_extra = dict(manifest) if isinstance(manifest, Mapping) else {}
            for key in ("topic_fit", "decision_criteria", "failure_mode"):
                if key in spec and key not in manifest_extra:
                    manifest_extra[key] = spec[key]

            drafts.append(
                Draft(
                    persona_id=persona_id,
                    name=name,
                    role=role,
                    intent=intent,
                    allowed_tools=allowed_tools,
                    required_outputs=required_outputs,
                    value_axes=value_axes,
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

    # ------------------------------------------------------------------
    # HACHIMI Neuro-Symbolic Deep Validator (PRD-v2 §5.2)
    # ------------------------------------------------------------------

    def deep_validate(
        self,
        drafts: Sequence[Draft],
        ontology: Mapping[str, Any],
        topic_keywords: Optional[Sequence[str]] = None,
        diversity_map: Any = None,
        topic: Optional[str] = None,
    ) -> ValidationReport:
        """Fast 통과한 페르소나에만 적용되는 깊은 검증.

        - Korean real-name targeting (실명 + 직책 패턴) 차단
        - 토픽 관련성 (keyword overlap, 0.3 미만이면 reject)
        - MAP-Elites 다양성은 generate/finalize 단계에서 coverage telemetry로 기록

        LLM 호출 없이 stdlib만으로 동작 — Phase 2에서 LLM judge 추가 가능.
        """
        issues: List[ValidationIssue] = []
        valid_ids: List[str] = []
        topic_set = {str(k).strip().lower() for k in (topic_keywords or []) if str(k).strip()}
        resolved_topic = topic or _topic_from_keywords(topic_keywords, ontology)

        for draft in drafts:
            persona_issues: List[ValidationIssue] = []
            text_lower = _manifest_text(draft.to_manifest()).lower()

            # Korean real-name + 직책 패턴 차단
            if _KOREAN_NAME_RX.search(text_lower) or _KOREAN_NAME_RX.search(text_lower.replace(" ", " ")):
                persona_issues.append(
                    _issue(draft, "deep.korean_real_name", "Korean real-name targeting suspected")
                )
            for tok in _KOREAN_DOXX_TOKENS:
                if tok in text_lower:
                    persona_issues.append(
                        _issue(draft, "deep.pii_token", f"PII-style token present: {tok}")
                    )

            # 토픽 관련성 (keyword overlap)
            if topic_set:
                relevance = _topic_relevance(text_lower, topic_set)
                if relevance < 0.3:
                    persona_issues.append(
                        _issue(
                            draft,
                            "deep.topic_relevance",
                            f"topic relevance {relevance:.2f} < 0.3",
                        )
                    )

            if self.gateway is not None:
                persona_issues.extend(
                    self._deep_validate_llm(draft, ontology, resolved_topic)
                )

            if persona_issues:
                issues.extend(persona_issues)
            else:
                valid_ids.append(draft.persona_id)

        return ValidationReport(valid_ids=valid_ids, issues=issues)

    def _deep_validate_llm(
        self,
        draft: Draft,
        ontology: Mapping[str, Any],
        topic: str,
    ) -> List[ValidationIssue]:
        """Ask the LLM judge whether a draft is topic-relevant."""

        if self.gateway is None:
            return []
        prompt = build_persona_deep_validate_prompt(draft, ontology, topic)
        try:
            result = self.gateway.call("council", prompt)
            score, reason, issues = parse_persona_validation_response(result.text)
        except LiveModeViolation:
            raise
        except Exception:
            return []
        if score < 0.3:
            detail = reason or "; ".join(issues) or f"LLM relevance {score:.2f} < 0.3"
            return [_issue(draft, "deep.llm_topic_relevance", detail)]
        return []

    # ------------------------------------------------------------------
    # HACHIMI 3-iter Revise Loop (PRD-v2 §5.2 Stage 3)
    # ------------------------------------------------------------------

    def revise_drafts(
        self,
        drafts: Sequence[Draft],
        report: ValidationReport,
        ontology: Mapping[str, Any],
    ) -> List[Draft]:
        """검증 실패 Draft를 수정해 새 Draft 시퀀스 반환.

        실패 코드별 자동 수정 전략:
            - ontology.tools     -> 허용 도구만 남김
            - ontology.outputs   -> 누락 산출물 추가
            - ontology.role      -> 첫 허용 role로 교체
            - aup.denied_term    -> intent에서 해당 term 제거
            - aup.risk           -> intent를 안전 템플릿으로 강등
            - lockdown           -> intent를 안전 템플릿으로 강등
            - value_axes         -> 기본 값으로 재초기화

        deep.* 코드는 propose 단계에서 처리 — 여기서는 fast 코드만 다룸.
        """
        allowed_tools = set(_string_list(ontology.get("allowed_tools")))
        required_outputs = _string_list(ontology.get("required_outputs"))
        roles = _string_list(ontology.get("roles"))

        new_drafts: List[Draft] = []
        for draft in drafts:
            persona_issues = report.issues_for(draft.persona_id)
            if not persona_issues:
                new_drafts.append(draft)
                continue

            codes = {issue.code for issue in persona_issues}
            new_intent = draft.intent
            new_tools = list(draft.allowed_tools)
            new_outputs = list(draft.required_outputs)
            new_role = draft.role
            new_axes = dict(draft.value_axes)

            if "ontology.tools" in codes and allowed_tools:
                new_tools = [t for t in new_tools if t in allowed_tools]
                if not new_tools:
                    new_tools = sorted(allowed_tools)[:1]

            if "ontology.outputs" in codes and required_outputs:
                for out in required_outputs:
                    if out not in new_outputs:
                        new_outputs.append(out)

            if "ontology.role" in codes and roles:
                new_role = roles[0]

            if {"aup.denied_term", "aup.risk", "lockdown"} & codes:
                new_intent = _SAFE_FALLBACK_INTENT

            if "value_axes" in codes:
                new_axes = dict(DEFAULT_VALUE_AXES)

            new_drafts.append(
                replace(
                    draft,
                    intent=new_intent,
                    allowed_tools=new_tools,
                    required_outputs=new_outputs,
                    role=new_role,
                    value_axes=new_axes,
                )
            )
        return new_drafts

    # ------------------------------------------------------------------
    # End-to-end HACHIMI generator
    # ------------------------------------------------------------------

    def generate(
        self,
        ontology: Mapping[str, Any],
        target_count: int,
        seed_personas: Optional[Sequence[Mapping[str, Any]]] = None,
        max_revisions: int = 3,
        diversity_map: Any = None,
        topic_keywords: Optional[Sequence[str]] = None,
        topic: Optional[str] = None,
    ) -> Tuple[List[FinalPersona], Dict[str, Any]]:
        """propose → fast validate → (revise → re-validate) ×3 → deep validate → MAP-Elites → finalize.

        Returns:
            (finals, telemetry) — telemetry 키:
                ``revisions_used``, ``fast_failed_ids``, ``deep_failed_ids``,
                ``fallbacks_used``, ``coverage_after_admit``
        """
        if self.gateway is not None and not seed_personas:
            resolved_topic = topic or _topic_from_keywords(topic_keywords, ontology)
            drafts = self.propose_with_llm(
                ontology,
                target_count=target_count,
                topic=resolved_topic,
            )
        else:
            resolved_topic = topic or _topic_from_keywords(topic_keywords, ontology)
            drafts = self.propose(ontology, target_count=target_count, seed_personas=seed_personas)

        return self.finalize_drafts(
            drafts,
            ontology,
            target_count=target_count,
            max_revisions=max_revisions,
            diversity_map=diversity_map,
            topic_keywords=topic_keywords,
            topic=resolved_topic,
            allow_fallbacks=True,
        )

    def finalize_drafts(
        self,
        drafts: Sequence[Draft],
        ontology: Mapping[str, Any],
        *,
        target_count: int | None = None,
        max_revisions: int = 3,
        diversity_map: Any = None,
        topic_keywords: Optional[Sequence[str]] = None,
        topic: Optional[str] = None,
        allow_fallbacks: bool = True,
        revision_notes: Optional[Sequence[str]] = None,
    ) -> Tuple[List[FinalPersona], Dict[str, Any]]:
        """Run already-proposed Drafts through the full HACHIMI/MAP-Elites path."""

        resolved_target = len(drafts) if target_count is None else max(int(target_count), 0)
        resolved_topic = topic or _topic_from_keywords(topic_keywords, ontology)
        drafts = list(drafts)
        telemetry: Dict[str, Any] = {
            "revisions_used": 0,
            "fast_failed_ids": [],
            "deep_failed_ids": [],
            "fallbacks_used": 0,
            "coverage_after_admit": 0.0,
            "target_count": resolved_target,
        }

        # Fast loop with up to max_revisions iterations
        for iteration in range(max_revisions):
            report = self.validate(drafts, ontology, value_axes_required=True)
            if report.ok:
                break
            telemetry["revisions_used"] = iteration + 1
            drafts = self.revise_drafts(drafts, report, ontology)

        final_fast = self.validate(drafts, ontology, value_axes_required=True)
        telemetry["fast_failed_ids"] = [
            d.persona_id for d in drafts if d.persona_id not in final_fast.valid_ids
        ]
        survivors = [d for d in drafts if d.persona_id in final_fast.valid_ids]

        # Deep validation
        deep_report = self.deep_validate(
            survivors,
            ontology,
            topic_keywords=topic_keywords,
            diversity_map=diversity_map,
            topic=resolved_topic,
        )
        telemetry["deep_failed_ids"] = [
            d.persona_id for d in survivors if d.persona_id not in deep_report.valid_ids
        ]
        deep_survivors = [d for d in survivors if d.persona_id in deep_report.valid_ids]

        # MAP-Elites records diversity coverage. It does not cap the full
        # MiroFish-style persona pool; many personas may share a cell, while
        # the map keeps the best representative for coverage telemetry.
        if diversity_map is not None and hasattr(diversity_map, "admit"):
            for draft in deep_survivors:
                axes = draft.to_manifest().get("value_axes") or {}
                diversity_map.admit(draft.persona_id, axes, fitness=1.0)
            telemetry["coverage_after_admit"] = float(diversity_map.coverage())

        # Build finals from the full validated pool, not only MAP-Elites cells.
        finals: List[FinalPersona] = []
        extra_notes = list(revision_notes or [])
        for draft in deep_survivors:
            manifest = draft.to_manifest()
            manifest.setdefault("value_axes", dict(DEFAULT_VALUE_AXES))
            finals.append(
                FinalPersona(
                    persona_id=draft.persona_id,
                    name=draft.name,
                    role=draft.role,
                    manifest=manifest,
                    revision_notes=extra_notes + [
                        "validated_against_ontology",
                        "lockdown_checked",
                        "deep_validated",
                    ],
                )
            )

        # Fallback fill — under target_count → safe preset
        shortage = resolved_target - len(finals)
        if allow_fallbacks and shortage > 0:
            for i in range(shortage):
                fb = _build_fallback_persona(ontology, len(finals) + 1)
                finals.append(fb)
            telemetry["fallbacks_used"] = shortage

        telemetry["persona_pool_size"] = len(finals)
        return finals, telemetry


# ---------- module-level helpers --------------------------------------------


_SAFE_FALLBACK_INTENT = "Summarize grounded evidence and report uncertainty without suggesting risky actions."


def _topic_relevance(text_lower: str, topic_set: set) -> float:
    """간단한 keyword overlap 기반 0~1 관련성 점수."""
    if not topic_set:
        return 1.0
    hits = sum(1 for kw in topic_set if kw in text_lower)
    return hits / max(len(topic_set), 1)


def _build_fallback_persona(ontology: Mapping[str, Any], index: int) -> FinalPersona:
    """모든 검증을 통과하는 안전 프리셋 페르소나."""
    roles = _string_list(ontology.get("roles")) or ["evidence_reviewer"]
    allowed_tools = _string_list(ontology.get("allowed_tools")) or ["read_file"]
    required_outputs = _string_list(ontology.get("required_outputs")) or ["report"]

    persona_id = f"persona-fallback-{index:03d}"
    role = roles[0]
    manifest = {
        "intent": _SAFE_FALLBACK_INTENT,
        "allowed_tools": list(allowed_tools[:1]),
        "required_outputs": list(required_outputs),
        "role": role,
        "value_axes": dict(DEFAULT_VALUE_AXES),
        "fallback": True,
    }
    return FinalPersona(
        persona_id=persona_id,
        name=f"Fallback {role.replace('_', ' ').title()} {index}",
        role=role,
        manifest=manifest,
        revision_notes=["fallback_safe_preset"],
    )


def _string_list(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, Iterable):
        return [str(item) for item in value if str(item)]
    return []


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _topic_from_keywords(
    topic_keywords: Optional[Sequence[str]],
    ontology: Mapping[str, Any],
) -> str:
    ontology_topic = _clean_text(ontology.get("topic") or ontology.get("research_question"))
    if ontology_topic:
        return ontology_topic
    keywords = [str(keyword).strip() for keyword in (topic_keywords or []) if str(keyword).strip()]
    return ", ".join(keywords) if keywords else "general research topic"


def _value_axes(value: Any) -> Dict[str, Any]:
    if isinstance(value, Mapping):
        axes = dict(DEFAULT_VALUE_AXES)
        axes.update(value)
        return axes
    return dict(DEFAULT_VALUE_AXES)


def _value_axes_for_index(
    base_axes: Mapping[str, Any],
    index: int,
    target_count: int,
) -> Dict[str, Any]:
    axes = dict(base_axes)
    if target_count <= 1:
        return axes

    # MiroFish-style large pools need spread across the MAP-Elites plane.
    # Keep non-numeric axes from ontology, but distribute the two diversity
    # axes deterministically so hundreds of personas do not collapse into one
    # default cell.
    grid = max(2, int((target_count - 1) ** 0.5) + 1)
    row = index // grid
    col = index % grid
    axes["risk_tolerance"] = round((col + 0.5) / grid, 4)
    axes["innovation_orientation"] = round((row + 0.5) / grid, 4)
    return axes


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
