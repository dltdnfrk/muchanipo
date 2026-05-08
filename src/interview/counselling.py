"""Ontology-first Deep Interview counselling for the intake interview.

The legacy interview path is rubric/format driven: Q1..Q6 are fixed PRD
slots and ``office_hours.reframe_with_context`` only rewrites their wording with
small heuristics.  That is useful for tests, but it does not behave like a
product strategist reading the user's references and counselling them toward a
better PRD.

This module adds a thin LLM counselling layer while keeping deterministic
fallbacks for offline tests.  The LLM is asked to produce one adaptive ontology
extraction question for the currently uncovered internal rubric dimension,
grounded in:

- the original idea/topic,
- all previous answers,
- known/background/reference material already supplied by the user, and
- the target downstream document contract.

It must not blindly ask the generic Q1..Q6 wording; it should challenge vague
assumptions, stabilize ambiguous nouns/entities/relations, and ask a single
high-leverage follow-up.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from src.intent.office_hours import reframe_with_context
from src.interview.ontology_state import (
    InterviewOntologyState,
    UnknownSlot,
    build_interview_ontology_state,
    question_quality_gate,
)


@dataclass(frozen=True)
class CounsellingTurn:
    """One adaptive counselling question ready for the JSON-line protocol."""

    dim_id: str
    question: str
    options: list[dict[str, str]] = field(default_factory=list)
    rationale: str = ""
    reference_insights: list[str] = field(default_factory=list)
    assumptions_to_test: list[str] = field(default_factory=list)
    prd_impact: str = ""
    ontology_state: dict[str, Any] = field(default_factory=dict)
    ontology_delta: dict[str, Any] = field(default_factory=dict)
    unknowns: list[dict[str, Any]] = field(default_factory=list)
    targets_unknown_ids: list[str] = field(default_factory=list)
    question_quality_gate: dict[str, Any] = field(default_factory=dict)
    provider: str = "heuristic"
    model: str = "fallback"
    fallback_reason: str = ""

    def to_framed_question(self) -> dict[str, Any]:
        return {
            "dim_id": self.dim_id,
            "question": self.question,
            "options": self.options,
            "ontology_state": self.ontology_state,
            "ontology_delta": self.ontology_delta,
            "unknowns": self.unknowns,
            "targets_unknown_ids": self.targets_unknown_ids,
            "question_quality_gate": self.question_quality_gate,
            "counselling": {
                "mode": "llm_counselling" if self.provider != "heuristic" else "heuristic_counselling_fallback",
                "rationale": self.rationale,
                "reference_insights": self.reference_insights,
                "assumptions_to_test": self.assumptions_to_test,
                "prd_impact": self.prd_impact,
                "ontology_state": self.ontology_state,
                "ontology_delta": self.ontology_delta,
                "unknowns": self.unknowns,
                "targets_unknown_ids": self.targets_unknown_ids,
                "question_quality_gate": self.question_quality_gate,
                "provider": self.provider,
                "model": self.model,
                "fallback_reason": self.fallback_reason,
            },
        }


def ask_prd_counselling_question(
    dim_id: str,
    topic: str,
    prev_answers: Mapping[str, str] | None = None,
    *,
    gateway: Any | None = None,
    options: Sequence[Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    """Return an adaptive counselling question for the current PRD dimension.

    ``gateway`` is intentionally dependency-injected so tests can pass a fake
    provider and the app can pass GatewayV2.  If the call fails or the model
    returns non-JSON, we fall back to a deterministic counselling-flavoured
    rewrite instead of the old bare template.
    """
    answers = dict(prev_answers or {})
    ontology_state = build_interview_ontology_state(topic, answers)
    base = reframe_with_context(dim_id, topic, answers)
    base_options = [dict(item) for item in (options or base.get("options") or [])]
    prompt = build_prd_counselling_prompt(
        dim_id=dim_id,
        topic=topic,
        prev_answers=answers,
        fallback_question=str(base.get("question") or dim_id),
        options=base_options,
        ontology_state=ontology_state,
    )
    if gateway is not None:
        try:
            result = gateway.call(stage="interview", prompt=prompt, temperature=0.2)
            parsed = _parse_model_json(str(getattr(result, "text", "")))
            turn = _turn_from_model_payload(
                dim_id=dim_id,
                payload=parsed,
                base_options=base_options,
                ontology_state=ontology_state,
                provider=str(getattr(result, "provider", "llm") or "llm"),
                model=str(getattr(result, "model", "unknown") or "unknown"),
            )
            if turn.question:
                return turn.to_framed_question()
        except Exception as exc:  # model unavailable or bad JSON: fallback below
            fallback = _fallback_counselling_turn(
                dim_id=dim_id,
                topic=topic,
                prev_answers=answers,
                base_question=str(base.get("question") or dim_id),
                options=base_options,
                ontology_state=ontology_state,
                fallback_reason=str(exc),
            )
            return fallback.to_framed_question()

    return _fallback_counselling_turn(
        dim_id=dim_id,
        topic=topic,
        prev_answers=answers,
        base_question=str(base.get("question") or dim_id),
        options=base_options,
        ontology_state=ontology_state,
    ).to_framed_question()


def build_prd_counselling_prompt(
    *,
    dim_id: str,
    topic: str,
    prev_answers: Mapping[str, str],
    fallback_question: str,
    options: Sequence[Mapping[str, str]],
    ontology_state: InterviewOntologyState | None = None,
) -> str:
    answer_lines = "\n".join(
        f"- {key}: {value}" for key, value in prev_answers.items() if str(value).strip()
    ) or "- (none yet)"
    reference_text = _reference_material(prev_answers)
    option_lines = "\n".join(
        f"- {item.get('label', '')}: {item.get('description', '')}" for item in options
    ) or "- 자유 답변 중심"
    ontology = ontology_state or build_interview_ontology_state(topic, prev_answers)
    ontology_json = json.dumps(ontology.to_dict(), ensure_ascii=False, indent=2)
    top_unknowns = "\n".join(
        f"- {unknown.id} | {unknown.kind} | {unknown.label} | entropy={unknown.entropy:.2f} | {unknown.why_it_matters}"
        for unknown in ontology.sorted_unknowns()[:5]
    ) or "- (no open unknowns detected)"
    return f"""
You are Muchanipo's Deep Interview interviewer for ontology extraction, not a
PRD form generator.
Your job is to infer what the user is *really asking*, expose the hidden domain
objects/actors/relations in their idea, and ask ONE incisive follow-up that
forces conceptual precision.

Deep Interview principles:
- Do NOT simply repeat a fixed Q1..Q6 template or ask a generic PRD slot.
- Do NOT ask generic decision-form questions such as "what decision will you
  make after this?" unless the user already clarified the ontology and the only
  missing piece is decision governance.
- Act like a Socratic product/research interviewer: push on ambiguous nouns,
  causal links, user segments, workflows, constraints, evidence boundaries, and
  category definitions.
- First identify the likely ontology: entities, actors, actions, triggers,
  measurable states, constraints, evidence types, and excluded meanings.
- Ask the next question that most improves that ontology, even if it does not
  match the nominal Q1..Q6 slot.
- Use the user's exact topic terms; do not replace them with generic terms like
  "market", "purpose", "deliverable", or "quality" unless needed.
- If the topic is vague, ask the user to choose between competing interpretations
  of the topic, not to fill a PRD field.
- Ask exactly one main question. You may include 2-3 concrete contrast probes in
  the same question if they help the user answer precisely.
- Keep the question in Korean unless the user's material is mostly English.
- Return strict JSON only; no markdown fence.
- The question must target at least one named unknown from the Open unknowns
  list unless there are no open unknowns.
- Name the targeted unknown in the question text so the user knows why this is
  being asked.

Current PRD dimension: {dim_id}
Original topic / idea:
{topic}

Previous answers:
{answer_lines}

Reference/background material detected from user answers:
{reference_text}

Existing fallback question, only for safety; improve it substantially:
{fallback_question}

Existing UI option hints, if useful:
{option_lines}

Current ontology state:
{ontology_json}

Open unknowns, ordered by entropy:
{top_unknowns}

Return JSON with this schema:
{{
  "ontology_delta": {{
    "entities": [],
    "relations": [],
    "excluded_meanings": [],
    "evidence_boundaries": []
  }},
  "unknowns": [
    {{
      "id": "reuse-or-create-stable-id",
      "kind": "ambiguous_term|missing_actor|missing_workflow|evidence_gap|boundary_gap",
      "label": "named unknown",
      "why_it_matters": "why this blocks ontology/execution quality",
      "candidate_interpretations": ["..."],
      "entropy": 0.0
    }}
  ],
  "next_question": {{
    "question": "adaptive counselling question in Korean",
    "rationale": "why this is the highest leverage follow-up",
    "targets_unknown_ids": ["unknown-id"]
  }},
  "reference_insights": ["insight from provided references/background"],
  "assumptions_to_test": ["assumption that must be tested before ontology/execution"],
  "prd_impact": "which downstream ontology/capability/research section improves if user answers this",
  "options": [{{"label": "...", "description": "...", "recommended": "true|false"}}]
}}
""".strip()


def _turn_from_model_payload(
    *,
    dim_id: str,
    payload: Mapping[str, Any],
    base_options: list[dict[str, str]],
    ontology_state: InterviewOntologyState,
    provider: str,
    model: str,
) -> CounsellingTurn:
    next_question = payload.get("next_question") if isinstance(payload.get("next_question"), Mapping) else {}
    question = _clean(next_question.get("question") if isinstance(next_question, Mapping) else "")
    if not question:
        question = _clean(payload.get("question"))
    unknowns = _payload_unknowns(payload.get("unknowns")) or ontology_state.sorted_unknowns()
    targets_unknown_ids = _string_list(
        next_question.get("targets_unknown_ids") if isinstance(next_question, Mapping) else payload.get("targets_unknown_ids")
    )
    if not targets_unknown_ids and unknowns:
        targets_unknown_ids = [unknowns[0].id]
    gate = question_quality_gate(
        question=question,
        unknowns=unknowns,
        targets_unknown_ids=targets_unknown_ids,
    )
    if _is_generic_form_question(question) or not gate["passed"]:
        question = ""
    options = _normalize_options(payload.get("options")) or base_options
    ontology_delta = _normalize_ontology_delta(payload.get("ontology_delta"))
    ontology_state_dict = ontology_state.to_dict()
    ontology_state_dict["unknowns"] = [_unknown_to_dict(unknown) for unknown in unknowns]
    return CounsellingTurn(
        dim_id=dim_id,
        question=question,
        options=options,
        rationale=_clean(next_question.get("rationale") if isinstance(next_question, Mapping) else payload.get("rationale")),
        reference_insights=_string_list(payload.get("reference_insights")),
        assumptions_to_test=_string_list(payload.get("assumptions_to_test")),
        prd_impact=_clean(payload.get("prd_impact")),
        ontology_state=ontology_state_dict,
        ontology_delta=ontology_delta,
        unknowns=[_unknown_to_dict(unknown) for unknown in unknowns],
        targets_unknown_ids=targets_unknown_ids,
        question_quality_gate=gate,
        provider=provider,
        model=model,
    )


def _fallback_counselling_turn(
    *,
    dim_id: str,
    topic: str,
    prev_answers: Mapping[str, str],
    base_question: str,
    options: list[dict[str, str]],
    ontology_state: InterviewOntologyState,
    fallback_reason: str = "",
) -> CounsellingTurn:
    refs = _reference_insights(prev_answers, topic)
    assumption = _dimension_assumption(dim_id, topic, prev_answers)
    question = _fallback_question(dim_id, topic, prev_answers, base_question, refs, assumption)
    unknowns = ontology_state.sorted_unknowns()
    targets_unknown_ids = [unknowns[0].id] if unknowns else []
    gate = question_quality_gate(
        question=question,
        unknowns=unknowns,
        targets_unknown_ids=targets_unknown_ids,
    )
    return CounsellingTurn(
        dim_id=dim_id,
        question=question,
        options=options,
        rationale="LLM 상담 질문을 사용할 수 없을 때도 참고자료·이전 답변을 반영해 가장 큰 불확실성을 묻습니다.",
        reference_insights=refs,
        assumptions_to_test=[assumption] if assumption else [],
        prd_impact=_prd_impact(dim_id),
        ontology_state=ontology_state.to_dict(),
        ontology_delta={
            "entities": ontology_state.to_dict().get("entities", []),
            "relations": ontology_state.to_dict().get("relations", []),
            "excluded_meanings": ontology_state.excluded_meanings,
            "evidence_boundaries": ontology_state.evidence_boundaries,
        },
        unknowns=[_unknown_to_dict(unknown) for unknown in unknowns],
        targets_unknown_ids=targets_unknown_ids,
        question_quality_gate=gate,
        provider="heuristic",
        model="fallback",
        fallback_reason=fallback_reason,
    )


def _fallback_question(
    dim_id: str,
    topic: str,
    prev_answers: Mapping[str, str],
    base_question: str,
    refs: list[str],
    assumption: str,
) -> str:
    subject = _short(topic)
    ref_clause = f" 참고자료/배경에서 보이는 핵심 단서({'; '.join(refs[:2])})를 기준으로," if refs else ""
    if dim_id == "Q1_research_question":
        return f"'{subject}'에서 사용자가 진짜 묻고 싶은 대상은 무엇인가요?{ref_clause} 예를 들어 '누가/무엇을/어떤 상황에서/어떤 신호를 근거로/어떤 행동으로 바꾸는지'를 한 문장으로 좁혀주세요. 단순 주제명이 아니라 핵심 개체·행위·관계가 드러나야 합니다."
    if dim_id == "Q2_purpose":
        return f"'{subject}' 안에 섞여 있는 서로 다른 해석을 먼저 갈라볼게요.{ref_clause} 지금 알고 싶은 것은 ①사용자가 겪는 문제 구조, ②기술/데이터가 판별해야 하는 상태, ③돈을 내거나 도입하는 조건 중 무엇인가요? 하나를 고르고, 왜 다른 해석은 1차 질문이 아닌지도 말해주세요."
    if dim_id == "Q3_context":
        return f"'{subject}'가 실제로 발생하는 장면을 온톨로지처럼 쪼개면, 핵심 행위자는 누구이고 어떤 트리거가 어떤 행동/결과로 이어지나요?{ref_clause} '사용자-상황-신호-행동-결과' 관계를 최대한 구체적으로 답해주세요."
    if dim_id == "Q4_known":
        return f"'{subject}'에서 이미 안다고 생각하지만 사실 정의가 흔들리는 용어는 무엇인가요?{ref_clause} 예: 대상 사용자, 진단/판별 기준, 저비용의 기준, 재택/현장/실험실의 경계처럼, 리서치 전에 먼저 고정해야 할 개념 2-3개를 골라주세요."
    if dim_id == "Q5_deliverable":
        return f"'{subject}'를 산출물로 바로 만들기 전에, 먼저 확정해야 할 개념 지도는 무엇인가요?{ref_clause} 핵심 엔티티, 속성, 관계, 금지해야 할 오해를 적어주면 그걸 바탕으로 PRD 구조를 만들겠습니다."
    if dim_id == "Q6_quality":
        return f"'{subject}'에 대한 좋은 답과 나쁜 답을 가르는 경계는 무엇인가요?{ref_clause} 어떤 증거가 나오면 '이 개념 정의가 맞다/틀리다'고 판단할 수 있는지, 반례까지 포함해 알려주세요."
    return base_question


def _dimension_assumption(dim_id: str, topic: str, prev_answers: Mapping[str, str]) -> str:
    joined = " ".join([topic, *prev_answers.values()]).lower()
    if dim_id in {"Q1_research_question", "Q2_purpose"}:
        return "사용자가 말한 핵심 명사가 하나의 안정된 개체/상태/행위로 정의될 수 있다는 가정"
    if dim_id == "Q3_context":
        return "하나의 초기 사용자군/상황으로 좁힐 수 있다는 가정"
    if dim_id == "Q4_known":
        return "제공된 참고자료가 현재 시장/기술 현실을 대표한다는 가정"
    if dim_id == "Q5_deliverable":
        return "정리된 개념 지도와 제외 의미가 산출물 구조로 바로 변환 가능하다는 가정"
    if "시장" in joined or "가격" in joined or "구매" in joined:
        return "시장성 판단에 필요한 가격·구매·채널 근거를 확보할 수 있다는 가정"
    return "현재 정보만으로 핵심 개체·관계·증거 경계를 확정할 수 있다는 가정"


def _prd_impact(dim_id: str) -> str:
    return {
        "Q1_research_question": "ontology.core_question / core entity-action relation",
        "Q2_purpose": "ontology.interpretation_boundary / primary question type",
        "Q3_context": "ontology.actors_triggers_workflows / target scenario",
        "Q4_known": "ontology.definitions_constraints / reference grounding",
        "Q5_deliverable": "ontology.entity_relation_map / downstream spec structure",
        "Q6_quality": "ontology.evidence_boundaries / falsification criteria",
    }.get(dim_id, "ontology extraction fields")


_GENERIC_FORM_PATTERNS = (
    "무엇을 만들거나 검증",
    "어떤 결정이나 산출물",
    "답을 얻은 뒤 어떤 결정",
    "PRD 개요",
    "핵심 가치는 무엇",
    "요구사항→기능→상세기능",
    "성공 지표와 근거 품질",
    "what decision",
    "what deliverable",
)


def _is_generic_form_question(question: str) -> bool:
    lowered = question.lower()
    return any(pattern.lower() in lowered for pattern in _GENERIC_FORM_PATTERNS)


def _reference_material(prev_answers: Mapping[str, str]) -> str:
    refs = []
    for key in ("known", "context", "quality_bar", "research_question", "purpose"):
        value = _clean(prev_answers.get(key))
        if value:
            refs.append(f"- {key}: {value}")
    return "\n".join(refs) if refs else "- (no explicit references/background yet)"


def _reference_insights(prev_answers: Mapping[str, str], topic: str) -> list[str]:
    candidates = []
    for key in ("known", "context", "quality_bar", "purpose", "research_question"):
        candidates.extend(_split_phrases(str(prev_answers.get(key) or "")))
    if not candidates:
        candidates = _split_phrases(topic)
    return [_clean(item) for item in candidates if _clean(item)][:4]


def _parse_model_json(text: str) -> Mapping[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if not match:
            raise
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("counselling model returned non-object JSON")
    return value


def _normalize_options(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    normalized = []
    for item in raw[:5]:
        if not isinstance(item, Mapping):
            continue
        label = _clean(item.get("label"))
        description = _clean(item.get("description"))
        if not label and not description:
            continue
        normalized.append(
            {
                "label": label or description[:40],
                "description": description or label,
                "recommended": str(item.get("recommended", "")).lower() in {"1", "true", "yes"},
            }
        )
    return normalized


def _normalize_ontology_delta(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        return {"entities": [], "relations": [], "excluded_meanings": [], "evidence_boundaries": []}
    return {
        "entities": _mapping_list(raw.get("entities")),
        "relations": _mapping_list(raw.get("relations")),
        "excluded_meanings": _string_list(raw.get("excluded_meanings")),
        "evidence_boundaries": _string_list(raw.get("evidence_boundaries")),
    }


def _payload_unknowns(raw: Any) -> list[UnknownSlot]:
    unknowns: list[UnknownSlot] = []
    for item in _mapping_list(raw):
        kind = _clean(item.get("kind")) or "ambiguous_term"
        label = _clean(item.get("label")) or "핵심 개체"
        unknowns.append(
            UnknownSlot(
                id=_clean(item.get("id")) or f"{kind}:{_simple_slug(label)}",
                kind=kind,
                label=label,
                why_it_matters=_clean(item.get("why_it_matters")),
                candidate_interpretations=_string_list(item.get("candidate_interpretations")),
                entropy=_float_between_zero_one(item.get("entropy"), default=1.0),
                resolved=str(item.get("resolved", "")).lower() in {"1", "true", "yes"},
            )
        )
    return unknowns[:8]


def _unknown_to_dict(unknown: UnknownSlot) -> dict[str, Any]:
    return {
        "id": unknown.id,
        "kind": unknown.kind,
        "label": unknown.label,
        "why_it_matters": unknown.why_it_matters,
        "candidate_interpretations": list(unknown.candidate_interpretations),
        "entropy": unknown.entropy,
        "resolved": unknown.resolved,
    }


def _mapping_list(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, Mapping)]


def _float_between_zero_one(raw: Any, *, default: float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = default
    return max(0.0, min(1.0, value))


def _simple_slug(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣_-]+", "-", value).strip("-")[:48] or "unknown"


def _string_list(raw: Any) -> list[str]:
    if isinstance(raw, str):
        return [_clean(raw)] if _clean(raw) else []
    if not isinstance(raw, Sequence):
        return []
    values = []
    for item in raw:
        cleaned = _clean(item)
        if cleaned:
            values.append(cleaned)
    return values[:6]


def _split_phrases(value: str) -> list[str]:
    return [
        part.strip(" -•\t\r\n")
        for part in re.split(r"[;\n]+|,\s*(?=[가-힣A-Za-z0-9])", value or "")
        if part.strip(" -•\t\r\n")
    ]


def _short(value: str, limit: int = 56) -> str:
    cleaned = _clean(value)
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1].rstrip() + "…"


def _clean(value: Any) -> str:
    return " ".join(str(value or "").strip().split())
