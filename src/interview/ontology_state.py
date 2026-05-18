"""Ontology state and unknown detection for Muchanipo Deep Interview.

The interview can keep legacy Q1..Q6 IDs for compatibility, but the runtime
state should be an ontology-under-construction: entities, relations, unresolved
unknowns, excluded meanings, and evidence boundaries.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class OntologyEntity:
    id: str
    label: str
    kind: str  # actor | object | system | event | signal | state | constraint | evidence
    description: str = ""
    confidence: float = 0.0
    source_turn_ids: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)
    uncertainty: float = 1.0
    status: str = "supported"


@dataclass(frozen=True)
class OntologyRelation:
    source: str
    predicate: str  # uses | triggers | observes | pays_for | decides | blocks | evidences
    target: str
    confidence: float = 0.0
    source_turn_ids: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)
    uncertainty: float = 1.0
    status: str = "supported"


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


ONTOLOGY_EXTRACTION_STAGE_ID = "ontology_extraction"
ONTOLOGY_EXTRACTION_ARTIFACT_CONTRACT = "ontology_extraction_stage_artifact.v1"
ONTOLOGY_EXTRACTION_RUBRIC_VERSION = "goals-loop2-ontology-extraction.v1"
ONTOLOGY_TOPIC_ANCHOR_REF = "topic:anchor"

ONTOLOGY_DOWNSTREAM_CONSUMERS: tuple[str, ...] = (
    "persona_generation",
    "llm_council",
    "final_report_html_yaml",
)

ONTOLOGY_RELATION_VOCABULARY: tuple[str, ...] = (
    "causes",
    "prevents",
    "enables",
    "requires",
    "contradicts",
    "supports",
    "defines",
    "instantiates",
    "contains",
    "part_of",
    "measures",
    "affects",
    "correlates_with",
    "precedes",
    "follows",
    "authored_by",
    "stakeholder_of",
    "evaluated_by",
    "validated_by",
    "derived_from",
)

ONTOLOGY_FAILURE_MODES: tuple[str, ...] = (
    "unsupported_entities_need_review",
    "blocked_ontology_too_sparse",
    "blocked_identifier_conflict",
    "blocked_sensitive_entity",
    "missing_source_grounding",
    "missing_consumability_check",
)


@dataclass(frozen=True)
class OntologyExtractionArtifactInput:
    """Inputs for the standalone GOALS ontology_extraction artifact."""

    topic: str
    interview_turns: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    source_fragments: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    aliases: Mapping[str, Sequence[str]] = field(default_factory=dict)
    relations: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    rejected_extractions: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    manual_entities: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)


def build_ontology_extraction_stage_artifact(
    artifact_input: OntologyExtractionArtifactInput,
) -> dict[str, Any]:
    """Build a consumable, source-grounded GOALS ontology stage artifact."""

    ontology = build_source_grounded_ontology_artifact(artifact_input)
    needs_review_count = len(ontology["needs_review_entity_labels"])
    blockers = _ontology_blockers(ontology)
    blocker_codes = [str(blocker["code"]) for blocker in blockers]
    status = "blocked" if blockers else "completed"
    blocker_code = blocker_codes[0] if blocker_codes else ""
    relation_count = len(ontology["relations"])
    entity_count = len(ontology["entities"])
    rejected_count = len(ontology["rejected_extractions"])
    progress_percent = 65.0 if status == "blocked" else 100.0

    from src.pipeline.goals_artifacts import build_goals_stage_artifact

    return build_goals_stage_artifact(
        ONTOLOGY_EXTRACTION_STAGE_ID,
        status=status,
        inputs=[
            {"artifact_id": "topic", "present": bool(str(artifact_input.topic).strip())},
            {"artifact_id": "interview_turns", "count": len(artifact_input.interview_turns)},
            {"artifact_id": "source_fragments", "count": len(artifact_input.source_fragments)},
        ],
        outputs=[
            {
                "artifact_id": "ontology_extraction",
                "contract": ONTOLOGY_EXTRACTION_ARTIFACT_CONTRACT,
                "present": True,
                "payload": ontology,
            },
            {
                "artifact_id": "consumability_check",
                "present": True,
                "payload": {
                    "consumability": ontology["consumability"],
                    "downstream_consumability": ontology["downstream_consumability"],
                    "gap_records": ontology["gap_records"],
                },
            },
        ],
        blockers=blockers,
        gates=[
            {
                "gate_id": "ontology_consumability",
                "status": "failed" if blockers else "passed",
                "required_for": list(ONTOLOGY_DOWNSTREAM_CONSUMERS),
                "checks": ontology["consumability"],
                "downstream_consumability": ontology["downstream_consumability"],
            }
        ],
        human_decision={
            "required": bool(blockers),
            "status": "pending" if blockers else "not_required",
            "mode": "review_ontology_consumability" if blockers else "",
            "rationale": (
                "Ontology blockers prevent silent persona/council consumption."
                if blockers
                else "Ontology is source-grounded and downstream-consumable."
            ),
            "required_action": _ontology_required_action(blocker_code),
        },
        evidence_refs=_artifact_evidence_refs(ontology),
        source_refs=_artifact_source_refs(ontology),
        metrics={
            "entity_count": entity_count,
            "relation_count": relation_count,
            "alias_count": sum(len(item.get("aliases", [])) for item in ontology["entities"]),
            "needs_review_entity_count": needs_review_count,
            "supported_entity_count": sum(
                1 for item in ontology["entities"] if item.get("status") == "supported"
            ),
            "supported_relation_count": sum(
                1 for item in ontology["relations"] if item.get("status") == "supported"
            ),
            "rejected_extraction_count": rejected_count,
            "gap_count": len(ontology["gap_records"]),
            "consumable": ontology["consumable"],
            "persona_generation_ready": ontology["downstream_consumability"]["persona_generation_ready"],
            "llm_council_ready": ontology["downstream_consumability"]["llm_council_ready"],
        },
        progress_percent=progress_percent,
        legacy_subactivity={
            "subactivity": "source_grounded_ontology_extraction",
            "downstream_consumers": list(ONTOLOGY_DOWNSTREAM_CONSUMERS),
        },
        hermes_scoring={
            "score": 5.0 if not blockers else 3.0,
            "readiness": "ready" if not blockers else "needs_review",
            "confidence": _average_confidence(ontology["entities"]),
            "rubric_version": ONTOLOGY_EXTRACTION_RUBRIC_VERSION,
            "issues": blocker_codes,
        },
        retry={
            "retryable": bool(blockers),
            "next_action": _ontology_required_action(blocker_code) if blockers else "consume_downstream",
        },
        failure_semantics={
            "code": blocker_code,
            "terminal": False,
            "retryable": bool(blockers),
            "failure_modes": list(ONTOLOGY_FAILURE_MODES),
        },
        metadata={
            "specific_contract": ONTOLOGY_EXTRACTION_ARTIFACT_CONTRACT,
            "claim_boundary": (
                "Ontology extraction uses explicit source/interview evidence and marks "
                "unsupported candidates as needs_review instead of rebuilding hidden ontology from topic strings."
            ),
            **dict(artifact_input.metadata),
        },
    )


def build_source_grounded_ontology_artifact(
    artifact_input: OntologyExtractionArtifactInput,
) -> dict[str, Any]:
    source_texts = _source_text_records(artifact_input)
    source_ref_index = {str(item.get("source_ref") or "") for item in source_texts}
    corpus = " ".join(item["text"] for item in source_texts)
    entities_by_label: dict[str, dict[str, Any]] = {}

    for label in list(dict.fromkeys([*_candidate_entity_labels(artifact_input.topic, corpus), *artifact_input.aliases.keys()])):
        refs = _refs_for_label(label, source_texts)
        if refs:
            entities_by_label[label] = _artifact_entity(
                label=label,
                kind=_entity_kind(label),
                aliases=list(artifact_input.aliases.get(label, []) or []),
                source_refs=refs,
                confidence=0.72 if label == artifact_input.topic else 0.64,
            )

    for raw in artifact_input.manual_entities:
        if not isinstance(raw, Mapping):
            continue
        label = str(raw.get("label") or raw.get("name") or "").strip()
        if not label:
            continue
        refs = _string_list(raw.get("source_refs") or raw.get("source_ref"))
        if not refs:
            refs = _refs_for_label(label, source_texts)
        entities_by_label[label] = _artifact_entity(
            label=label,
            kind=str(raw.get("kind") or raw.get("type") or _entity_kind(label)),
            aliases=[
                *list(artifact_input.aliases.get(label, []) or []),
                *_string_list(raw.get("aliases")),
            ],
            source_refs=refs,
            confidence=float(raw.get("confidence") or (0.68 if refs else 0.35)),
        )

    relations = _artifact_relations(artifact_input.relations, entities_by_label, source_texts)
    rejected_extractions = [
        _rejected_extraction(item)
        for item in artifact_input.rejected_extractions
        if isinstance(item, Mapping)
    ]
    rejected_extractions.extend(_auto_rejected_extractions(entities_by_label.values(), relations))
    needs_review = sorted(
        entity["label"] for entity in entities_by_label.values() if entity["status"] == "needs_review"
    )
    gap_records = _ontology_gap_records(entities_by_label.values(), relations)
    downstream_consumability = _downstream_consumability(
        entities_by_label.values(),
        relations,
        gap_records,
    )
    consumability = _ontology_consumability(
        entities_by_label.values(),
        relations,
        needs_review=needs_review,
        source_ref_index=source_ref_index,
        downstream_consumability=downstream_consumability,
    )
    consumable = all(value is True for value in consumability.values())
    return {
        "schema_version": 1,
        "artifact_id": "ontology_extraction",
        "contract": ONTOLOGY_EXTRACTION_ARTIFACT_CONTRACT,
        "ontology_id": f"ontology:{_slug(artifact_input.topic)}",
        "topic": artifact_input.topic,
        "domain_boundary": str(artifact_input.metadata.get("domain_boundary") or artifact_input.topic),
        "entities": sorted(entities_by_label.values(), key=lambda item: item["normalized_id"]),
        "nodes": sorted(entities_by_label.values(), key=lambda item: item["normalized_id"]),
        "relations": relations,
        "edges": relations,
        "alias_resolutions": _alias_resolutions(entities_by_label.values()),
        "uncertainty_summary": _uncertainty_summary(entities_by_label.values(), relations),
        "gap_records": gap_records,
        "rejected_extractions": rejected_extractions,
        "needs_review_entity_labels": needs_review,
        "needs_review_relation_ids": [
            str(relation.get("id") or relation.get("edge_id"))
            for relation in relations
            if relation.get("status") == "needs_review"
        ],
        "relation_vocabulary": list(ONTOLOGY_RELATION_VOCABULARY),
        "consumability": consumability,
        "downstream_consumability": downstream_consumability,
        "consumable": consumable,
    }


def ontology_extraction_stage_artifact_contract_report() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "contract": ONTOLOGY_EXTRACTION_ARTIFACT_CONTRACT,
        "stage_id": ONTOLOGY_EXTRACTION_STAGE_ID,
        "builder": "build_ontology_extraction_stage_artifact",
        "required_inputs": ["topic", "interview_turns", "source_fragments"],
        "relation_vocabulary": list(ONTOLOGY_RELATION_VOCABULARY),
        "required_outputs": [
            "ontology_id",
            "domain_boundary",
            "source_grounded_entities",
            "source_grounded_relations",
            "normalized_identifiers",
            "relations",
            "aliases",
            "alias_resolutions",
            "uncertainty",
            "uncertainty_summary",
            "rejected_extractions",
            "gap_records",
            "unsupported_entity_needs_review_state",
            "consumability_check",
            "downstream_consumability",
        ],
        "required_entity_fields": [
            "node_id",
            "normalized_id",
            "label",
            "kind",
            "aliases",
            "source_refs",
            "evidence_refs",
            "support_status",
            "status",
            "uncertainty",
        ],
        "required_relation_fields": [
            "edge_id",
            "source_id",
            "target_id",
            "relation",
            "predicate",
            "domain_predicate",
            "source_refs",
            "evidence_refs",
            "support_status",
            "status",
            "polarity",
            "uncertainty",
        ],
        "downstream_consumers": list(ONTOLOGY_DOWNSTREAM_CONSUMERS),
        "failure_modes": list(ONTOLOGY_FAILURE_MODES),
        "blocker_states": [
            "unsupported_entities_need_review",
            "blocked_ontology_too_sparse",
            "blocked_identifier_conflict",
            "blocked_sensitive_entity",
        ],
        "downstream_rules": {
            "persona_generation": (
                "Requires supported ontology nodes, role candidates, no blocking gaps, "
                "and direct consumption of the ontology_extraction payload."
            ),
            "llm_council": (
                "Requires at least one supported source-grounded edge with "
                "supports/contradicts polarity and represented central claims."
            ),
        },
        "compatibility": (
            "Downstream stages consume ontology_extraction output directly; topic strings are fallback display labels, not hidden ontology sources."
        ),
    }


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


def _source_text_records(artifact_input: OntologyExtractionArtifactInput) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    if str(artifact_input.topic).strip():
        records.append({"source_ref": ONTOLOGY_TOPIC_ANCHOR_REF, "turn_id": "", "text": str(artifact_input.topic).strip()})
    for idx, turn in enumerate(artifact_input.interview_turns, start=1):
        if not isinstance(turn, Mapping):
            continue
        source_ref = str(turn.get("source_ref") or turn.get("turn_id") or f"interview:turn-{idx}")
        turn_id = str(turn.get("turn_id") or source_ref)
        text = " ".join(
            str(turn.get(key) or "") for key in ("question", "answer", "text")
        ).strip()
        if text:
            records.append({"source_ref": source_ref, "turn_id": turn_id, "text": text})
    for idx, fragment in enumerate(artifact_input.source_fragments, start=1):
        if not isinstance(fragment, Mapping):
            continue
        source_ref = str(fragment.get("source_ref") or fragment.get("id") or f"source:fragment-{idx}")
        text = str(fragment.get("text") or fragment.get("quote") or fragment.get("claim") or "").strip()
        if text:
            records.append({"source_ref": source_ref, "turn_id": "", "text": text})
    return records


def _candidate_entity_labels(topic: str, corpus: str) -> list[str]:
    labels: list[str] = []
    topic = str(topic or "").strip()
    if topic:
        labels.append(topic)
    actor_patterns = (
        r"([0-9가-힣A-Za-z\s]{2,40}(?:사용자|고객|보호자|담당자|의사결정자|구매자|승인자))",
        r"([0-9가-힣A-Za-z\s]{2,40}(?:신호|workflow|워크플로우|시스템|플랫폼|SaaS))",
    )
    for pattern in actor_patterns:
        for match in re.findall(pattern, corpus or ""):
            cleaned = " ".join(str(match).split())
            cleaned = re.sub(r"^(?:에서|그리고|또는|사용자가|고객이)\s+", "", cleaned).strip()
            if 2 <= len(cleaned) <= 60:
                labels.append(cleaned)
    for token in _tokens(corpus):
        if len(token) >= 2:
            labels.append(token)
    return list(dict.fromkeys(labels))[:24]


def _refs_for_label(label: str, source_texts: Sequence[Mapping[str, str]]) -> list[str]:
    label_text = str(label or "").strip()
    label_tokens = [token for token in _tokens(label_text) if len(token) >= 2]
    refs: list[str] = []
    for record in source_texts:
        text = str(record.get("text") or "")
        if label_text and label_text in text:
            refs.append(str(record.get("source_ref") or ""))
            continue
        if label_tokens and all(token in text for token in label_tokens[:3]):
            refs.append(str(record.get("source_ref") or ""))
    return [ref for ref in dict.fromkeys(refs) if ref]


def _artifact_entity(
    *,
    label: str,
    kind: str,
    aliases: Sequence[str],
    source_refs: Sequence[str],
    confidence: float,
) -> dict[str, Any]:
    normalized_id = f"entity:{_slug(label)}"
    refs = [str(ref) for ref in dict.fromkeys(source_refs) if str(ref)]
    score = max(0.0, min(1.0, float(confidence)))
    evidence_refs = _non_topic_refs(refs)
    support_status = _support_status_for_refs(refs)
    status = {
        "supported": "supported",
        "topic_anchor_only": "rejected",
    }.get(support_status, "needs_review")
    return {
        "id": normalized_id,
        "node_id": normalized_id,
        "normalized_id": normalized_id,
        "label": str(label),
        "kind": str(kind or "object"),
        "aliases": list(dict.fromkeys(str(item) for item in aliases if str(item))),
        "attributes": {},
        "source_refs": refs,
        "evidence_refs": evidence_refs,
        "confidence": round(score, 3),
        "uncertainty": round(1.0 - score, 3),
        "support_status": support_status,
        "status": status,
        "provenance": {
            "extraction_method": "deterministic_source_grounded_ontology",
            "source_refs": refs,
            "evidence_refs": evidence_refs,
        },
    }


def _artifact_relations(
    raw_relations: Sequence[Mapping[str, Any]],
    entities_by_label: dict[str, dict[str, Any]],
    source_texts: Sequence[Mapping[str, str]],
) -> list[dict[str, Any]]:
    relations: list[dict[str, Any]] = []
    for raw in raw_relations:
        if not isinstance(raw, Mapping):
            continue
        source_label = str(raw.get("source") or "").strip()
        target_label = str(raw.get("target") or "").strip()
        predicate = str(raw.get("predicate") or "related_to").strip()
        if not source_label or not target_label:
            continue
        for label in (source_label, target_label):
            if label not in entities_by_label:
                refs = _string_list(raw.get("source_refs") or raw.get("source_ref")) or _refs_for_label(label, source_texts)
                entities_by_label[label] = _artifact_entity(
                    label=label,
                    kind=_entity_kind(label),
                    aliases=[],
                    source_refs=refs,
                        confidence=float(raw.get("confidence") or (0.62 if refs else 0.35)),
                )
        refs = _string_list(raw.get("source_refs") or raw.get("source_ref"))
        if not refs:
            refs = _relation_refs_for_labels(source_label, target_label, source_texts)
        source_id = entities_by_label[source_label]["normalized_id"]
        target_id = entities_by_label[target_label]["normalized_id"]
        confidence = max(0.0, min(1.0, float(raw.get("confidence") or 0.55)))
        support_status = _support_status_for_refs(refs)
        status = "supported" if support_status == "supported" else "needs_review"
        canonical_relation = _canonical_relation(predicate)
        polarity = _relation_polarity(raw, canonical_relation)
        relation_id = f"relation:{_slug(source_id + ':' + canonical_relation + ':' + target_id)}"
        evidence_refs = _non_topic_refs(refs)
        relations.append(
            {
                "id": relation_id,
                "edge_id": relation_id,
                "from_node_id": source_id,
                "to_node_id": target_id,
                "source_id": source_id,
                "predicate": canonical_relation,
                "relation": canonical_relation,
                "domain_predicate": predicate,
                "target_id": target_id,
                "source_refs": refs,
                "evidence_refs": evidence_refs,
                "confidence": round(confidence, 3),
                "uncertainty": round(1.0 - confidence, 3),
                "support_status": support_status,
                "status": status,
                "polarity": polarity,
                "provenance": {
                    "extraction_method": "deterministic_source_grounded_ontology",
                    "source_refs": refs,
                    "evidence_refs": evidence_refs,
                },
            }
        )
    return relations


def _ontology_consumability(
    entities: Sequence[Mapping[str, Any]],
    relations: Sequence[Mapping[str, Any]],
    *,
    needs_review: Sequence[str],
    source_ref_index: set[str],
    downstream_consumability: Mapping[str, Any],
) -> dict[str, bool]:
    supported_entities = [entity for entity in entities if entity.get("status") == "supported"]
    supported_relations = [relation for relation in relations if relation.get("status") == "supported"]
    non_topic_refs = {
        ref
        for item in [*entities, *relations]
        for ref in _non_topic_refs(_string_list(item.get("source_refs")))
    }
    known_non_topic_refs = {
        ref for ref in non_topic_refs if not source_ref_index or ref in source_ref_index
    }
    has_normalized_identifiers = bool(entities) and all(
        bool(entity.get("normalized_id")) and bool(entity.get("node_id")) for entity in entities
    )
    return {
        "has_source_grounded_entities": bool(supported_entities),
        "has_non_topic_source_grounding": bool(known_non_topic_refs),
        "has_normalized_identifiers": has_normalized_identifiers,
        "has_source_grounded_relations": bool(supported_relations),
        "has_relations": bool(relations),
        "has_aliases_field": all("aliases" in entity for entity in entities),
        "has_uncertainty": all("uncertainty" in item for item in [*entities, *relations]),
        "unsupported_entities_resolved": not needs_review,
        "downstream_must_use_artifact": _downstream_artifact_consumption_required(
            entities,
            relations,
            downstream_consumability,
        ),
        "persona_generation_ready": bool(downstream_consumability.get("persona_generation_ready")),
        "llm_council_ready": bool(downstream_consumability.get("llm_council_ready")),
    }


def _downstream_artifact_consumption_required(
    entities: Sequence[Mapping[str, Any]],
    relations: Sequence[Mapping[str, Any]],
    downstream_consumability: Mapping[str, Any],
) -> bool:
    """Derive the no-hidden-rebuild contract from consumable artifact content.

    Downstream stages must not silently rebuild ontology from the topic string, but the
    direct-consumption contract is only available when canonical, source-supported
    nodes and edges are present and downstream gates are ready. Sparse or
    topic-anchor-only artifacts fail closed instead of advertising a usable contract.
    """

    supported_entities = [entity for entity in entities if entity.get("status") == "supported"]
    supported_relations = [relation for relation in relations if relation.get("status") == "supported"]
    has_canonical_supported_nodes = bool(supported_entities) and all(
        bool(entity.get("normalized_id")) and bool(entity.get("node_id"))
        for entity in supported_entities
    )
    has_canonical_supported_edges = bool(supported_relations) and all(
        bool(relation.get("edge_id") or relation.get("id"))
        and bool(relation.get("source_id"))
        and bool(relation.get("target_id"))
        for relation in supported_relations
    )
    has_downstream_readiness_contract = all(
        bool(downstream_consumability.get(key))
        for key in ("persona_generation_ready", "llm_council_ready", "final_report_html_yaml_ready")
    )
    return bool(
        has_canonical_supported_nodes
        and has_canonical_supported_edges
        and has_downstream_readiness_contract
    )


def _downstream_consumability(
    entities: Sequence[Mapping[str, Any]],
    relations: Sequence[Mapping[str, Any]],
    gap_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    supported_entities = [entity for entity in entities if entity.get("status") == "supported"]
    supported_relations = [relation for relation in relations if relation.get("status") == "supported"]
    role_candidates = [
        entity
        for entity in supported_entities
        if str(entity.get("kind") or "") in {"actor", "organization", "stakeholder", "research_topic", "research"}
    ]
    blocking_gaps = [gap for gap in gap_records if gap.get("severity") == "blocker"]
    council_edges = [
        relation
        for relation in supported_relations
        if str(relation.get("polarity") or "") in {"supports", "contradicts"}
    ]
    persona_ready = bool(supported_entities and role_candidates and not blocking_gaps)
    council_ready = bool(council_edges and not blocking_gaps)
    return {
        "persona_generation_ready": persona_ready,
        "llm_council_ready": council_ready,
        "final_report_html_yaml_ready": bool(supported_entities and not blocking_gaps),
        "role_candidate_node_ids": [
            str(entity.get("normalized_id") or entity.get("node_id"))
            for entity in role_candidates
        ],
        "council_edge_ids": [
            str(relation.get("edge_id") or relation.get("id"))
            for relation in council_edges
        ],
        "refusal_reasons": _downstream_refusal_reasons(
            supported_entities=supported_entities,
            role_candidates=role_candidates,
            council_edges=council_edges,
            blocking_gaps=blocking_gaps,
        ),
    }


def _downstream_refusal_reasons(
    *,
    supported_entities: Sequence[Mapping[str, Any]],
    role_candidates: Sequence[Mapping[str, Any]],
    council_edges: Sequence[Mapping[str, Any]],
    blocking_gaps: Sequence[Mapping[str, Any]],
) -> list[str]:
    reasons: list[str] = []
    if not supported_entities:
        reasons.append("no_supported_source_grounded_entities")
    if not role_candidates:
        reasons.append("no_role_candidate_nodes")
    if not council_edges:
        reasons.append("no_supported_support_or_contradiction_edges")
    reasons.extend(str(gap.get("gap_type") or gap.get("blocker_code") or "") for gap in blocking_gaps)
    return [reason for reason in dict.fromkeys(reasons) if reason]


def _ontology_gap_records(
    entities: Sequence[Mapping[str, Any]],
    relations: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    supported_entity_count = sum(1 for entity in entities if entity.get("status") == "supported")
    for entity in entities:
        support_status = str(entity.get("support_status") or "")
        if support_status == "supported":
            continue
        blocker_code = (
            "blocked_ontology_too_sparse"
            if support_status == "topic_anchor_only"
            else "unsupported_entities_need_review"
        )
        gaps.append(
            {
                "gap_type": support_status or "unsupported_entity",
                "blocker_code": blocker_code,
                "support_status": support_status or "unsupported",
                "severity": "warning" if support_status == "topic_anchor_only" else "blocker",
                "entity_id": str(entity.get("normalized_id") or entity.get("id") or ""),
                "label": str(entity.get("label") or ""),
                "source_refs": list(entity.get("source_refs") or []),
            }
        )
    if supported_entity_count == 0:
        gaps.append(
            {
                "gap_type": "missing_source_grounded_entity",
                "blocker_code": "blocked_ontology_too_sparse",
                "severity": "blocker",
                "source_refs": [],
            }
        )
    if not any(relation.get("status") == "supported" for relation in relations):
        gaps.append(
            {
                "gap_type": "missing_source_grounded_relation",
                "blocker_code": "blocked_ontology_too_sparse",
                "severity": "blocker",
                "source_refs": [],
            }
        )
    return gaps


def _ontology_blockers(ontology: Mapping[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    seen: set[str] = set()
    if ontology.get("consumable"):
        return blockers
    for gap in ontology.get("gap_records", []) or []:
        if not isinstance(gap, Mapping):
            continue
        if gap.get("severity") != "blocker":
            continue
        code = str(gap.get("blocker_code") or "blocked_ontology_too_sparse")
        if code in seen:
            continue
        seen.add(code)
        blockers.append(
            {
                "code": code,
                "message": _ontology_blocker_message(code),
                "severity": "blocker",
                "recoverable": True,
                "required_action": _ontology_required_action(code),
                "source_ref": ",".join(_string_list(gap.get("source_refs"))),
                "human_decision_required": True,
            }
        )
    if not blockers:
        blockers.append(
            {
                "code": "blocked_ontology_too_sparse",
                "message": _ontology_blocker_message("blocked_ontology_too_sparse"),
                "severity": "blocker",
                "recoverable": True,
                "required_action": _ontology_required_action("blocked_ontology_too_sparse"),
                "source_ref": "",
                "human_decision_required": True,
            }
        )
    return blockers


def _ontology_blocker_message(code: str) -> str:
    messages = {
        "unsupported_entities_need_review": (
            "Unsupported ontology entities require human review before persona/council consumption."
        ),
        "blocked_ontology_too_sparse": (
            "Ontology is too sparse or topic-anchor-only for downstream persona/council consumption."
        ),
        "blocked_identifier_conflict": "Ontology contains conflicting normalized identifiers.",
        "blocked_sensitive_entity": "Ontology contains a sensitive entity requiring review.",
    }
    return messages.get(code, "Ontology extraction is blocked.")


def _ontology_required_action(code: str) -> str:
    actions = {
        "unsupported_entities_need_review": "attach_source_evidence_reject_or_explicitly_approve_entities",
        "blocked_ontology_too_sparse": "add_non_topic_source_grounding_and_supported_relations",
        "blocked_identifier_conflict": "resolve_normalized_identifier_conflict",
        "blocked_sensitive_entity": "review_sensitive_entity_policy",
    }
    return actions.get(code, "resolve_ontology_consumability_blocker")


def _alias_resolutions(entities: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    resolutions: list[dict[str, Any]] = []
    for entity in entities:
        for alias in entity.get("aliases", []) or []:
            resolutions.append(
                {
                    "alias": str(alias),
                    "normalized_id": str(entity.get("normalized_id") or ""),
                    "label": str(entity.get("label") or ""),
                    "status": str(entity.get("status") or ""),
                    "source_refs": list(entity.get("source_refs") or []),
                }
            )
    return resolutions


def _uncertainty_summary(
    entities: Sequence[Mapping[str, Any]],
    relations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    values = [
        float(item.get("uncertainty") or 0.0)
        for item in [*entities, *relations]
        if isinstance(item, Mapping)
    ]
    needs_review = [
        str(item.get("label") or item.get("id") or item.get("edge_id"))
        for item in [*entities, *relations]
        if isinstance(item, Mapping) and item.get("status") == "needs_review"
    ]
    return {
        "mean_uncertainty": round(sum(values) / len(values), 3) if values else 1.0,
        "max_uncertainty": round(max(values), 3) if values else 1.0,
        "needs_review_count": len(needs_review),
        "needs_review_items": needs_review,
    }


def _auto_rejected_extractions(
    entities: Sequence[Mapping[str, Any]],
    relations: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    rejected: list[dict[str, str]] = []
    ontology_sparse = not any(entity.get("status") == "supported" for entity in entities) or not any(
        relation.get("status") == "supported" for relation in relations
    )
    for entity in entities:
        support_status = str(entity.get("support_status") or "")
        if support_status == "supported":
            continue
        if support_status == "topic_anchor_only" and not ontology_sparse:
            continue
        rejected.append(
            {
                "raw": str(entity.get("label") or ""),
                "reason": (
                    "topic_anchor_only_not_source_grounded"
                    if support_status == "topic_anchor_only"
                    else "unsupported_by_source_refs"
                ),
                "source_ref": ",".join(_string_list(entity.get("source_refs"))),
            }
        )
    for relation in relations:
        if relation.get("support_status") == "supported":
            continue
        rejected.append(
            {
                "raw": str(relation.get("domain_predicate") or relation.get("predicate") or ""),
                "reason": "relation_not_source_grounded",
                "source_ref": ",".join(_string_list(relation.get("source_refs"))),
            }
        )
    return rejected


def _rejected_extraction(raw: Mapping[str, Any]) -> dict[str, str]:
    return {
        "raw": str(raw.get("raw") or raw.get("label") or ""),
        "reason": str(raw.get("reason") or "unsupported"),
        "source_ref": str(raw.get("source_ref") or ""),
    }


def _relation_refs_for_labels(
    source_label: str,
    target_label: str,
    source_texts: Sequence[Mapping[str, str]],
) -> list[str]:
    source_tokens = [token for token in _tokens(source_label) if len(token) >= 2]
    target_tokens = [token for token in _tokens(target_label) if len(token) >= 2]
    refs: list[str] = []
    for record in source_texts:
        text = str(record.get("text") or "")
        source_hit = source_label in text or (
            bool(source_tokens) and any(token in text for token in source_tokens[:3])
        )
        target_hit = target_label in text or (
            bool(target_tokens) and any(token in text for token in target_tokens[:3])
        )
        if source_hit and target_hit:
            refs.append(str(record.get("source_ref") or ""))
    return [ref for ref in dict.fromkeys(refs) if ref]


def _support_status_for_refs(source_refs: Sequence[str]) -> str:
    refs = [str(ref) for ref in source_refs if str(ref)]
    if _non_topic_refs(refs):
        return "supported"
    if refs:
        return "topic_anchor_only"
    return "unsupported"


def _non_topic_refs(source_refs: Sequence[str]) -> list[str]:
    return [
        str(ref)
        for ref in dict.fromkeys(source_refs)
        if str(ref) and str(ref) != ONTOLOGY_TOPIC_ANCHOR_REF
    ]


def _canonical_relation(predicate: str) -> str:
    raw = str(predicate or "").strip().lower()
    aliases = {
        "scope": "defines",
        "scopes": "defines",
        "defines": "defines",
        "contain": "contains",
        "contains": "contains",
        "part_of": "part_of",
        "requires": "requires",
        "needs": "requires",
        "enables": "enables",
        "supports": "supports",
        "support": "supports",
        "contradicts": "contradicts",
        "contradict": "contradicts",
        "prevents": "prevents",
        "causes": "causes",
        "affects": "affects",
        "observes": "affects",
        "triggers": "causes",
        "evaluates": "evaluated_by",
        "evaluated_by": "evaluated_by",
        "validates": "validated_by",
        "validated_by": "validated_by",
        "authored_by": "authored_by",
        "derived_from": "derived_from",
        "stakeholder_of": "stakeholder_of",
        "measures": "measures",
        "correlates_with": "correlates_with",
        "precedes": "precedes",
        "follows": "follows",
        "instantiates": "instantiates",
    }
    return aliases.get(raw, "affects")


def _relation_polarity(raw: Mapping[str, Any], relation: str) -> str:
    explicit = str(raw.get("polarity") or "").strip().lower()
    if explicit in {"supports", "contradicts", "neutral"}:
        return explicit
    if relation in {"contradicts", "prevents"}:
        return "contradicts"
    return "supports"


def _artifact_evidence_refs(ontology: Mapping[str, Any]) -> list[str]:
    refs: list[str] = []
    for relation in ontology.get("relations", []) or []:
        if isinstance(relation, Mapping):
            refs.extend(_string_list(relation.get("evidence_refs") or relation.get("source_refs")))
    return list(dict.fromkeys(refs))


def _artifact_source_refs(ontology: Mapping[str, Any]) -> list[str]:
    refs: list[str] = []
    for entity in ontology.get("entities", []) or []:
        if isinstance(entity, Mapping):
            refs.extend(_string_list(entity.get("source_refs")))
    return list(dict.fromkeys(refs))


def _average_confidence(entities: Sequence[Mapping[str, Any]]) -> float:
    values = [float(entity.get("confidence") or 0.0) for entity in entities if isinstance(entity, Mapping)]
    if not values:
        return 0.0
    return round(sum(values) / len(values), 3)


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item)]
    return [str(value)] if str(value) else []


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
