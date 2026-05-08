"""Ontology state and unknown detection for Muchanipo Deep Interview.

The interview can keep legacy Q1..Q6 IDs for compatibility, but the runtime
state should be an ontology-under-construction: entities, relations, unresolved
unknowns, excluded meanings, and evidence boundaries.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class OntologyEntity:
    id: str
    label: str
    kind: str  # actor | object | system | event | signal | state | constraint | evidence
    description: str = ""
    confidence: float = 0.0
    source_turn_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class OntologyRelation:
    source: str
    predicate: str  # uses | triggers | observes | pays_for | decides | blocks | evidences
    target: str
    confidence: float = 0.0
    source_turn_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class UnknownSlot:
    id: str
    kind: str  # ambiguous_term | missing_actor | missing_workflow | evidence_gap | boundary_gap
    label: str
    why_it_matters: str
    candidate_interpretations: list[str] = field(default_factory=list)
    entropy: float = 1.0
    resolved: bool = False


@dataclass
class InterviewOntologyState:
    topic: str
    entities: list[OntologyEntity] = field(default_factory=list)
    relations: list[OntologyRelation] = field(default_factory=list)
    unknowns: list[UnknownSlot] = field(default_factory=list)
    excluded_meanings: list[str] = field(default_factory=list)
    evidence_boundaries: list[str] = field(default_factory=list)
    turn_count: int = 0
    coverage: float = 0.0

    def sorted_unknowns(self) -> list[UnknownSlot]:
        return sorted(
            [unknown for unknown in self.unknowns if not unknown.resolved],
            key=lambda unknown: (unknown.entropy, unknown.kind, unknown.label),
            reverse=True,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "entities": [asdict(entity) for entity in self.entities],
            "relations": [asdict(relation) for relation in self.relations],
            "unknowns": [asdict(unknown) for unknown in self.unknowns],
            "excluded_meanings": list(self.excluded_meanings),
            "evidence_boundaries": list(self.evidence_boundaries),
            "turn_count": self.turn_count,
            "coverage": round(float(self.coverage), 3),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "InterviewOntologyState":
        return cls(
            topic=str(payload.get("topic") or ""),
            entities=[
                OntologyEntity(**item)
                for item in _mapping_items(payload.get("entities"))
                if item.get("id") and item.get("label") and item.get("kind")
            ],
            relations=[
                OntologyRelation(**item)
                for item in _mapping_items(payload.get("relations"))
                if item.get("source") and item.get("predicate") and item.get("target")
            ],
            unknowns=[
                UnknownSlot(**item)
                for item in _mapping_items(payload.get("unknowns"))
                if item.get("id") and item.get("kind") and item.get("label")
            ],
            excluded_meanings=[str(item) for item in payload.get("excluded_meanings") or [] if str(item).strip()],
            evidence_boundaries=[str(item) for item in payload.get("evidence_boundaries") or [] if str(item).strip()],
            turn_count=int(payload.get("turn_count") or 0),
            coverage=float(payload.get("coverage") or 0.0),
        )


def build_interview_ontology_state(
    topic: str,
    prev_answers: Mapping[str, str] | None = None,
) -> InterviewOntologyState:
    """Build a deterministic ontology sketch from the topic and current answers.

    This is deliberately a conservative local heuristic. The LLM can improve it,
    but fallback mode still exposes named unknowns and asks targeted questions.
    """
    answers = dict(prev_answers or {})
    corpus = " ".join([str(topic or ""), *[str(value or "") for value in answers.values()]])
    entities = _extract_entities(corpus)
    unknowns = _detect_unknown_slots(str(topic or ""), answers, entities)
    evidence_boundaries = _extract_boundary_items(corpus, EVIDENCE_TERMS)
    excluded_meanings = _extract_boundary_items(corpus, EXCLUSION_TERMS)
    coverage = _coverage_from_unknowns(unknowns)
    return InterviewOntologyState(
        topic=str(topic or ""),
        entities=entities,
        relations=_infer_relations(entities, corpus),
        unknowns=unknowns,
        excluded_meanings=excluded_meanings,
        evidence_boundaries=evidence_boundaries,
        turn_count=len([value for value in answers.values() if str(value).strip()]),
        coverage=coverage,
    )


def question_quality_gate(
    *,
    question: str,
    unknowns: list[UnknownSlot],
    targets_unknown_ids: list[str],
) -> dict[str, Any]:
    """Evaluate whether an adaptive question really targets ontology uncertainty."""
    text = " ".join(str(question or "").split())
    target_set = {str(item) for item in targets_unknown_ids if str(item).strip()}
    open_unknowns = [unknown for unknown in unknowns if not unknown.resolved]
    target_unknowns = [unknown for unknown in open_unknowns if unknown.id in target_set]
    blocked_reasons: list[str] = []

    if not text:
        blocked_reasons.append("empty_question")
    lowered = text.lower()
    if any(pattern.lower() in lowered for pattern in GENERIC_FORM_PATTERNS):
        blocked_reasons.append("generic_form_question")
    if open_unknowns and not target_unknowns:
        blocked_reasons.append("missing_target_unknown")
    if target_unknowns:
        target_labels = [unknown.label for unknown in target_unknowns]
        if not any(label and label in text for label in target_labels):
            blocked_reasons.append("target_unknown_not_named")

    return {
        "passed": not blocked_reasons,
        "reasons": blocked_reasons,
        "targets_unknown_ids": list(target_set),
        "target_unknown_labels": [unknown.label for unknown in target_unknowns],
    }


GENERIC_FORM_PATTERNS = (
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

ACTOR_TERMS = (
    "사용자",
    "고객",
    "환자",
    "농가",
    "가구",
    "기업",
    "팀",
    "조직",
    "담당자",
    "구매자",
    "의사결정자",
    "payer",
    "buyer",
    "user",
    "customer",
)
DECISION_ACTOR_TERMS = ("구매", "결제", "도입", "지불", "승인", "예산", "계약", "buyer", "payer", "budget")
WORKFLOW_TERMS = ("트리거", "신호", "상황", "행동", "결과", "workflow", "trigger", "signal", "action", "outcome")
EVIDENCE_TERMS = ("근거", "증거", "출처", "논문", "통계", "데이터", "citation", "evidence", "source")
EXCLUSION_TERMS = ("제외", "아님", "않는", "범위", "경계", "exclude", "not", "boundary")


def _detect_unknown_slots(
    topic: str,
    answers: Mapping[str, str],
    entities: list[OntologyEntity],
) -> list[UnknownSlot]:
    corpus = " ".join([topic, *answers.values()])
    unknowns: list[UnknownSlot] = []
    ambiguous = _ambiguous_term(topic)
    if ambiguous:
        unknowns.append(
            _unknown(
                "ambiguous_term",
                ambiguous,
                "핵심 용어의 범위가 흔들리면 actor, workflow, evidence route가 모두 달라집니다.",
                ["넓은 범주", "좁은 operational state", "인접하지만 제외할 의미"],
                0.94,
            )
        )
    if not _contains_any(corpus, ACTOR_TERMS):
        unknowns.append(
            _unknown(
                "missing_actor",
                "핵심 행위자",
                "누가 문제를 겪고 누가 행동하는지 모르면 인터뷰와 실행 그래프의 주체가 비어 있습니다.",
                ["사용자", "구매/도입 주체", "운영 담당자"],
                0.9,
            )
        )
    elif not _contains_any(corpus, DECISION_ACTOR_TERMS):
        unknowns.append(
            _unknown(
                "missing_actor",
                "도입/결제/승인 주체",
                "사용자와 지불자 또는 승인자가 다르면 research facet과 persona constraint가 달라집니다.",
                ["실사용자", "구매자", "승인자", "운영자"],
                0.82,
            )
        )
    if not _contains_any(corpus, WORKFLOW_TERMS):
        unknowns.append(
            _unknown(
                "missing_workflow",
                "트리거→신호→행동 workflow",
                "실행 가능한 capability graph는 어떤 신호가 어떤 행동으로 이어지는지 알아야 합니다.",
                ["이벤트 발생", "관찰 신호", "사용자 행동", "결과 상태"],
                0.86,
            )
        )
    if not _contains_any(corpus, EXCLUSION_TERMS):
        unknowns.append(
            _unknown(
                "boundary_gap",
                "포함/제외 의미",
                "제외 의미가 없으면 리서치가 넓은 카테고리로 drift될 수 있습니다.",
                ["포함할 의미", "헷갈리지만 제외할 의미", "나중으로 미룰 의미"],
                0.78,
            )
        )
    if not _contains_any(corpus, EVIDENCE_TERMS):
        unknowns.append(
            _unknown(
                "evidence_gap",
                "증거 경계",
                "어떤 근거가 충분한지 모르면 mock, 추정, 실제 출처를 구분할 수 없습니다.",
                ["공식 통계", "논문", "현장 인터뷰", "가격/도입 데이터"],
                0.74,
            )
        )
    if not unknowns and len(entities) < 2:
        unknowns.append(
            _unknown(
                "ambiguous_term",
                "핵심 개체",
                "개체가 충분히 분리되지 않아 관계 그래프를 만들 수 없습니다.",
                ["actor", "object", "state"],
                0.7,
            )
        )
    return unknowns


def _unknown(
    kind: str,
    label: str,
    why: str,
    candidates: list[str],
    entropy: float,
) -> UnknownSlot:
    return UnknownSlot(
        id=f"{kind}:{_slug(label)}",
        kind=kind,
        label=label,
        why_it_matters=why,
        candidate_interpretations=candidates,
        entropy=entropy,
    )


def _extract_entities(corpus: str) -> list[OntologyEntity]:
    seen: set[str] = set()
    entities: list[OntologyEntity] = []
    for token in _tokens(corpus):
        if token in seen or len(token) < 2:
            continue
        kind = _entity_kind(token)
        if kind == "object" and len(entities) >= 8:
            continue
        seen.add(token)
        entities.append(
            OntologyEntity(
                id=f"{kind}:{_slug(token)}",
                label=token,
                kind=kind,
                confidence=0.55 if kind == "object" else 0.68,
            )
        )
    return entities[:12]


def _infer_relations(entities: list[OntologyEntity], corpus: str) -> list[OntologyRelation]:
    actor = next((entity for entity in entities if entity.kind == "actor"), None)
    signal = next((entity for entity in entities if entity.kind == "signal"), None)
    target = next((entity for entity in entities if entity.kind in {"object", "system", "state"}), None)
    relations: list[OntologyRelation] = []
    if actor and target:
        relations.append(
            OntologyRelation(
                source=actor.id,
                predicate="uses_or_is_affected_by",
                target=target.id,
                confidence=0.45,
            )
        )
    if signal and target:
        relations.append(
            OntologyRelation(
                source=signal.id,
                predicate="evidences",
                target=target.id,
                confidence=0.42,
            )
        )
    return relations


def _tokens(corpus: str) -> list[str]:
    values = re.findall(r"[A-Za-z][A-Za-z0-9+_.-]{1,}|[가-힣0-9]{2,}", corpus or "")
    stop = {"그리고", "또는", "무엇", "어떤", "이번", "현재", "기준", "분석", "검증", "리서치"}
    return [value for value in values if value not in stop]


def _entity_kind(token: str) -> str:
    lowered = token.lower()
    if _contains_any(token, ACTOR_TERMS):
        return "actor"
    if _contains_any(token, WORKFLOW_TERMS):
        return "signal"
    if _contains_any(token, EVIDENCE_TERMS):
        return "evidence"
    if lowered in {"saas", "api", "system", "platform"} or token.endswith("앱") or token.endswith("시스템"):
        return "system"
    if token.endswith("상태") or token.endswith("문제"):
        return "state"
    return "object"


def _ambiguous_term(topic: str) -> str:
    tokens = _tokens(topic)
    suffixes = (
        "의료",
        "진단",
        "시장성",
        "자동화",
        "워크플로우",
        "SaaS",
        "플랫폼",
        "시스템",
        "서비스",
        "게이트",
    )
    candidates = [token for token in tokens if any(token.endswith(suffix) for suffix in suffixes)]
    if candidates:
        return max(candidates, key=len)
    if tokens:
        return max(tokens, key=len)
    return "핵심 용어"


def _extract_boundary_items(corpus: str, markers: tuple[str, ...]) -> list[str]:
    parts = re.split(r"[\n;,.]+", corpus or "")
    return [
        part.strip()
        for part in parts
        if part.strip() and _contains_any(part, markers)
    ][:5]


def _coverage_from_unknowns(unknowns: list[UnknownSlot]) -> float:
    if not unknowns:
        return 1.0
    missing = min(1.0, sum(max(0.0, min(1.0, unknown.entropy)) for unknown in unknowns) / 5.0)
    return round(max(0.0, 1.0 - missing), 3)


def _contains_any(value: str, terms: tuple[str, ...]) -> bool:
    lowered = str(value or "").lower()
    return any(term.lower() in lowered for term in terms)


def _slug(value: str) -> str:
    cleaned = re.sub(r"\s+", "-", str(value or "").strip().lower())
    digest = hashlib.sha1(cleaned.encode("utf-8")).hexdigest()[:8]
    visible = re.sub(r"[^0-9a-zA-Z가-힣_-]+", "", cleaned)[:32] or "unknown"
    return f"{visible}-{digest}"


def _mapping_items(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, Mapping)]
