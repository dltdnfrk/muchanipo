"""Public GOALS stage contract for user-facing pipeline surfaces."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .stages import Stage


PUBLIC_GOALS_STAGE_IDS: tuple[str, ...] = (
    "idea_dump",
    "deep_interview",
    "deep_research_max",
    "plannotator_review",
    "ontology_extraction",
    "persona_generation",
    "llm_council",
    "final_report_html_yaml",
)


@dataclass(frozen=True)
class GoalsStageContract:
    order: int
    stage_id: str
    label_en: str
    label_ko: str
    purpose: str

    @property
    def id(self) -> str:
        """Stable public stage id used by external GOALS consumers."""
        return self.stage_id

    @property
    def legacy_stages(self) -> tuple[Stage, ...]:
        """Legacy runtime stages that this public stage summarizes.

        This is a compatibility projection only: the old runtime stages and
        internal substeps remain valid implementation details.
        """
        return GOALS_STAGE_LEGACY_STAGE_MAP[self.stage_id]

    def as_dict(self) -> dict[str, Any]:
        return {
            "order": self.order,
            "id": self.stage_id,
            "stage_id": self.stage_id,
            "label_en": self.label_en,
            "label_ko": self.label_ko,
            "purpose": self.purpose,
            "legacy_stage_ids": [stage.value for stage in self.legacy_stages],
        }


CANONICAL_GOALS_STAGES: tuple[GoalsStageContract, ...] = (
    GoalsStageContract(
        order=1,
        stage_id="idea_dump",
        label_en="Idea dump",
        label_ko="아이디어 접수",
        purpose=(
            "Capture the raw user idea, supplied context, constraints, run mode, "
            "uncertainty flags, and next-stage handoff without treating guesses as facts."
        ),
    ),
    GoalsStageContract(
        order=2,
        stage_id="deep_interview",
        label_en="Deep interview",
        label_ko="심층 인터뷰",
        purpose=(
            "Turn the initial idea into a research brief with objective, audience, "
            "domain boundary, assumptions, unknowns, hypotheses, non-goals, and "
            "decision criteria."
        ),
    ),
    GoalsStageContract(
        order=3,
        stage_id="deep_research_max",
        label_en="Deep Research Max",
        label_ko="심층 리서치 맥스",
        purpose=(
            "Plan and run source-backed research with query routes, source decisions, "
            "citation records, claim-evidence coverage, refutation attempts, and mode "
            "honesty."
        ),
    ),
    GoalsStageContract(
        order=4,
        stage_id="plannotator_review",
        label_en="Plannotator review",
        label_ko="플래노테이터 리뷰",
        purpose=(
            "Record reviewer approval, rejection, edits, annotations, applied or "
            "rejected deltas, and any human-review blocker before consequential "
            "downstream synthesis."
        ),
    ),
    GoalsStageContract(
        order=5,
        stage_id="ontology_extraction",
        label_en="Ontology extraction",
        label_ko="온톨로지 추출",
        purpose=(
            "Extract source-grounded entities, relations, aliases, attributes, "
            "stakeholders, uncertainty, and provenance for downstream personas, council "
            "critique, and final reporting."
        ),
    ),
    GoalsStageContract(
        order=6,
        stage_id="persona_generation",
        label_en="Persona generation",
        label_ko="페르소나 생성",
        purpose=(
            "Generate, validate, admit, reject, deduplicate, and schedule grounded "
            "review personas from approved research context and ontology."
        ),
    ),
    GoalsStageContract(
        order=7,
        stage_id="llm_council",
        label_en="LLM council",
        label_ko="LLM 카운슬",
        purpose=(
            "Run structured critique and chair synthesis with evidence references, "
            "disagreement records, confidence, and a bounded revise, rerun, or no-op "
            "decision."
        ),
    ),
    GoalsStageContract(
        order=8,
        stage_id="final_report_html_yaml",
        label_en="Final report HTML/YAML",
        label_ko="최종 HTML/YAML 보고서",
        purpose=(
            "Export the final HTML report, YAML report, evidence manifest, readiness "
            "verdict, and any approved knowledge-write record or explicit skipped state."
        ),
    ),
)


LEGACY_TO_CANONICAL_STAGE_MAP: dict[str, str] = {
    Stage.IDEA_DUMP.value: "idea_dump",
    "intake": "idea_dump",
    Stage.INTERVIEW.value: "deep_interview",
    Stage.TARGETING.value: "deep_research_max",
    Stage.RESEARCH.value: "deep_research_max",
    Stage.EVIDENCE.value: "deep_research_max",
    Stage.COUNCIL.value: "llm_council",
    Stage.REPORT.value: "final_report_html_yaml",
    Stage.VAULT.value: "final_report_html_yaml",
    Stage.AGENTS.value: "persona_generation",
    Stage.DONE.value: "final_report_html_yaml",
    "finalize": "final_report_html_yaml",
}


GOALS_STAGE_LEGACY_STAGE_MAP: dict[str, tuple[Stage, ...]] = {
    "idea_dump": (Stage.IDEA_DUMP,),
    "deep_interview": (Stage.INTERVIEW,),
    "deep_research_max": (Stage.TARGETING, Stage.RESEARCH, Stage.EVIDENCE),
    "plannotator_review": (),
    "ontology_extraction": (),
    "persona_generation": (Stage.AGENTS,),
    "llm_council": (Stage.COUNCIL,),
    "final_report_html_yaml": (Stage.REPORT, Stage.VAULT, Stage.DONE),
}


INTERNAL_SUBSTEP_TO_CANONICAL_STAGE_MAP: dict[str, str] = {
    "plan_review": "plannotator_review",
    "hitl_gate": "plannotator_review",
    "plannotator": "plannotator_review",
    "annotation_review": "plannotator_review",
    "annotation_delta": "plannotator_review",
    "interview_ontology_delta": "ontology_extraction",
    "ontology_state": "ontology_extraction",
    "source_ontology": "ontology_extraction",
    "gbrain_runtime": "ontology_extraction",
    "mirofish_world": "ontology_extraction",
    "persona_pool": "persona_generation",
    "persona_admission": "persona_generation",
    "persona_validation": "persona_generation",
    "speaker_schedule": "persona_generation",
    "council_trace": "llm_council",
    "chair_synthesis": "llm_council",
    "critique_to_action": "llm_council",
    "knowledge_write_gate": "final_report_html_yaml",
    "evidence_manifest": "final_report_html_yaml",
    "final_report": "final_report_html_yaml",
}


PUBLIC_GOALS_STAGES = CANONICAL_GOALS_STAGES


def canonical_stage_ids() -> tuple[str, ...]:
    return PUBLIC_GOALS_STAGE_IDS


def public_goals_stage_ids() -> list[str]:
    return list(PUBLIC_GOALS_STAGE_IDS)


def legacy_stages_for_public_stage(stage_id: str) -> tuple[Stage, ...]:
    try:
        return GOALS_STAGE_LEGACY_STAGE_MAP[str(stage_id)]
    except KeyError as exc:
        raise KeyError(f"unknown public GOALS stage: {stage_id}") from exc


def goals_stage_by_id(stage_id: str) -> GoalsStageContract:
    for stage in CANONICAL_GOALS_STAGES:
        if stage.stage_id == stage_id:
            return stage
    raise KeyError(f"unknown GOALS public stage: {stage_id}")


def public_stage_for_legacy(stage: str | Stage) -> str:
    key = stage.value if isinstance(stage, Stage) else str(stage)
    try:
        return LEGACY_TO_CANONICAL_STAGE_MAP[key]
    except KeyError as exc:
        raise KeyError(f"unknown legacy stage: {key}") from exc


def public_stage_for_internal_substep(substep: str) -> str:
    try:
        return INTERNAL_SUBSTEP_TO_CANONICAL_STAGE_MAP[str(substep)]
    except KeyError as exc:
        raise KeyError(f"unknown internal GOALS substep: {substep}") from exc


def normalize_public_stage(stage: str | Stage) -> str:
    key = stage.value if isinstance(stage, Stage) else str(stage)
    if key in PUBLIC_GOALS_STAGE_IDS:
        return key
    if key in LEGACY_TO_CANONICAL_STAGE_MAP:
        return LEGACY_TO_CANONICAL_STAGE_MAP[key]
    if key in INTERNAL_SUBSTEP_TO_CANONICAL_STAGE_MAP:
        return INTERNAL_SUBSTEP_TO_CANONICAL_STAGE_MAP[key]
    raise KeyError(f"unknown GOALS stage or substep: {key}")


def goals_stage_contract_report() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "contract": "public_goals_stages",
        "stage_ids": list(PUBLIC_GOALS_STAGE_IDS),
        "stages": [stage.as_dict() for stage in CANONICAL_GOALS_STAGES],
        "legacy_runtime_stage_contract": [stage.value for stage in Stage],
        "goals_stage_legacy_stage_map": {
            stage_id: [stage.value for stage in legacy_stages]
            for stage_id, legacy_stages in GOALS_STAGE_LEGACY_STAGE_MAP.items()
        },
        "legacy_stage_map": dict(LEGACY_TO_CANONICAL_STAGE_MAP),
        "internal_substep_map": dict(INTERNAL_SUBSTEP_TO_CANONICAL_STAGE_MAP),
        "compatibility": (
            "Legacy runtime stages and internal substeps remain valid only as "
            "implementation detail when mapped to one canonical public GOALS stage."
        ),
    }
