"""Expert interviewer policy for Muchanipo Deep Interview.

This module provides a Socratic ontology-extraction loop primitive. It is the
contract anchor for replacing the fixed Q1..Q6 form-fill sequence in
``src.muchanipo.server._collect_serve_interview_answers`` with a dynamic
gap-driven loop.

Design rules (driven by user requirement: "professional interview quality, not
PRD form completion"):

1.  Each turn is selected by **what's missing in the ontology**, not by rubric
    slot order.
2.  The loop terminates as soon as the ontology has enough structure to drive
    grounded research, even if that's after 2 turns.
3.  Hard cap (default 8) prevents runaway interviews.
4.  Question templates use the user's exact topic terms; never substitute
    generic words like "market" / "purpose" / "deliverable" / "quality".
5.  Question templates explicitly avoid the decision-form anti-pattern
    ("어떤 결정을 내릴 것인가" / "어떤 PRD를 만들 것인가") — these are reserved for
    governance review, not idea ontology extraction.

The module is intentionally LLM-agnostic: it returns ``SocraticTurn`` objects
that callers (server.py, persona generator, tests) can either render directly
or pass to an LLM for refinement. State updates are heuristic stubs — production
callers should swap in an LLM-driven extractor before persisting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class OntologyGap:
    """A specific concept-level missing piece in the user's idea ontology."""

    kind: str  # "entity" | "actor" | "relation" | "trigger" | "workflow"
    # | "constraint" | "evidence_boundary" | "excluded_meaning"
    label: str  # short human label of what's missing
    why_it_matters: str  # one-sentence rationale shown to user/LLM
    confidence: float  # 0.0..1.0 — how sure the policy is this gap exists


@dataclass(frozen=True)
class CandidateInterpretation:
    """One plausible reading of the user's idea, with key entities/actions."""

    label: str
    one_line: str
    key_entities: tuple[str, ...] = ()
    key_actions: tuple[str, ...] = ()
    excluded_meanings: tuple[str, ...] = ()


@dataclass(frozen=True)
class SocraticTurn:
    """A single expert-interviewer turn with explicit reasoning trace."""

    question: str
    target_gap: OntologyGap
    candidate_interpretations: tuple[CandidateInterpretation, ...]
    expected_ontology_progress: str  # what concept becomes well-defined if user answers
    rationale: str  # why this is highest-leverage now
    options: tuple[Mapping[str, str], ...] = ()  # optional contrast probes


@dataclass
class OntologyState:
    """Mutable ontology accumulated across turns.

    Used for stop-condition + gap detection. Callers may persist this between
    turns (e.g., on the InterviewSession) so the loop is resumable.
    """

    entities: dict[str, str] = field(default_factory=dict)  # name -> definition
    actors: dict[str, str] = field(default_factory=dict)
    relations: list[tuple[str, str, str]] = field(default_factory=list)  # (src, kind, dst)
    triggers: dict[str, str] = field(default_factory=dict)
    workflows: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    evidence_boundaries: list[str] = field(default_factory=list)
    excluded_meanings: list[str] = field(default_factory=list)
    raw_answers: list[str] = field(default_factory=list)

    @property
    def is_ready_for_research(self) -> bool:
        """Stop condition: enough ontology to drive grounded research.

        Required: 2+ entities, 1+ actor, 1+ workflow, AND at least one of
        (constraint | excluded_meaning) so council and source-channel routing
        have negative-space anchors.
        """
        return (
            len(self.entities) >= 2
            and len(self.actors) >= 1
            and len(self.workflows) >= 1
            and (len(self.constraints) >= 1 or len(self.excluded_meanings) >= 1)
        )

    @property
    def coverage_score(self) -> float:
        """0..1 score of ontology completeness. UI may display as progress bar."""
        slots = (
            min(1.0, len(self.entities) / 2.0),
            min(1.0, len(self.actors) / 1.0),
            min(1.0, len(self.workflows) / 1.0),
            min(1.0, max(len(self.constraints), len(self.excluded_meanings)) / 1.0),
            min(1.0, len(self.relations) / 1.0),
        )
        return sum(slots) / len(slots)


def detect_gaps(state: OntologyState) -> list[OntologyGap]:
    """Return ontology gaps ordered by importance (highest-leverage first)."""
    gaps: list[OntologyGap] = []
    if len(state.entities) < 2:
        gaps.append(OntologyGap(
            kind="entity",
            label="key domain entities",
            why_it_matters=(
                "Without 2+ defined entities, downstream research cannot scope "
                "sources or terms."
            ),
            confidence=0.9,
        ))
    if not state.actors:
        gaps.append(OntologyGap(
            kind="actor",
            label="primary actors / user roles",
            why_it_matters=(
                "A research wedge needs a known acting party "
                "(user, buyer, operator, regulator)."
            ),
            confidence=0.85,
        ))
    if not state.workflows:
        gaps.append(OntologyGap(
            kind="workflow",
            label="actual workflow context where the idea operates",
            why_it_matters=(
                "Concrete steps anchor evidence; abstract ideas drift toward "
                "generic claims."
            ),
            confidence=0.8,
        ))
    if not state.relations:
        gaps.append(OntologyGap(
            kind="relation",
            label="causal/structural relation between named concepts",
            why_it_matters=(
                "Named entities without relations leave the council without "
                "a graph to reason on."
            ),
            confidence=0.7,
        ))
    if not state.excluded_meanings and not state.constraints:
        gaps.append(OntologyGap(
            kind="excluded_meaning",
            label="what the idea explicitly is NOT about",
            why_it_matters=(
                "Negative space prevents off-topic source acceptance and "
                "persona drift."
            ),
            confidence=0.75,
        ))
    if not state.evidence_boundaries:
        gaps.append(OntologyGap(
            kind="evidence_boundary",
            label="kinds of evidence the user will and will not accept",
            why_it_matters=(
                "Early-stated boundaries prevent late-stage report rejection."
            ),
            confidence=0.6,
        ))
    return gaps


def next_expert_turn(
    *,
    topic: str,
    prior_turns: Sequence[Mapping[str, Any]],
    state: OntologyState,
    max_turns: int = 8,
    min_turns: int = 2,
) -> SocraticTurn | None:
    """Return the next high-leverage Socratic turn, or None if interview is done.

    Stop conditions (in order):
    1. ``len(prior_turns) >= max_turns`` (hard cap)
    2. ``state.is_ready_for_research and len(prior_turns) >= min_turns``

    The min_turns floor prevents the loop from terminating on the first turn
    even when the heuristic state-update happened to fill many slots from a
    single rich answer; we still want at least one disambiguation pass.
    """
    turn_count = len(prior_turns)
    if turn_count >= max_turns:
        return None
    if turn_count >= min_turns and state.is_ready_for_research:
        return None

    gaps = detect_gaps(state)
    if not gaps:
        return None

    # Pick the highest-confidence gap. Ties broken by detect_gaps() order.
    target = max(gaps, key=lambda g: g.confidence)

    return SocraticTurn(
        question=_socratic_question_template(target, topic=topic),
        target_gap=target,
        candidate_interpretations=_candidate_interpretations(topic=topic),
        expected_ontology_progress=f"{target.kind}: {target.label}",
        rationale=target.why_it_matters,
        options=_contrast_probes(target),
    )


def update_state_from_answer(
    state: OntologyState,
    *,
    gap: OntologyGap,
    answer: str,
) -> OntologyState:
    """Heuristic state update from a free-text user answer.

    For production-grade extraction, an LLM-driven update step should be used
    instead (e.g., extract entities + relations from the answer text). This
    helper is the deterministic fallback and the test contract anchor.
    """
    cleaned = answer.strip()
    if not cleaned:
        return state
    state.raw_answers.append(cleaned)

    if gap.kind == "entity":
        for line in cleaned.replace(",", "\n").split("\n"):
            line = line.strip()
            if line and len(state.entities) < 5:
                key = line.split(":")[0].strip()[:80]
                if key:
                    state.entities.setdefault(key, line)
    elif gap.kind == "actor":
        first = cleaned.split("\n")[0][:80]
        if first:
            state.actors.setdefault(first, cleaned)
    elif gap.kind == "workflow":
        state.workflows.append(cleaned)
    elif gap.kind == "relation":
        for line in cleaned.split("\n"):
            normalized = line.replace("->", " → ").replace("→", " → ")
            parts = [p.strip() for p in normalized.split(" → ") if p.strip()]
            if len(parts) >= 2:
                state.relations.append((parts[0], "relates_to", parts[1]))
    elif gap.kind == "excluded_meaning":
        state.excluded_meanings.append(cleaned)
    elif gap.kind == "constraint":
        state.constraints.append(cleaned)
    elif gap.kind == "evidence_boundary":
        state.evidence_boundaries.append(cleaned)
    elif gap.kind == "trigger":
        first = cleaned.split("\n")[0][:80]
        if first:
            state.triggers.setdefault(first, cleaned)
    return state


def _socratic_question_template(gap: OntologyGap, *, topic: str) -> str:
    """Per-gap Socratic question that uses the user's exact topic terms.

    Hard rules enforced by design:
    - Never use "market" / "purpose" / "deliverable" / "quality" as standalone
      generic substitutes for the user's domain language.
    - Never ask "what decision will you make" or "what PRD will you build" —
      those are decision-governance questions, not ontology questions.
    """
    subject = topic.strip().split("\n")[0][:120] or "이 아이디어"

    if gap.kind == "entity":
        return (
            f"'{subject}'에서 가장 중요한 도메인 객체 2-3개를 정의해주세요. "
            "각각 무엇이 핵심 속성이고, 비슷해 보이지만 다른 객체와 어떻게 구분되는지 "
            "한 줄로 적어주세요."
        )
    if gap.kind == "actor":
        return (
            f"'{subject}'를 실제로 사용하거나 그 결과로 행동이 바뀌는 사람/조직은 누구인가요? "
            "1순위 actor와, 그 actor가 행동을 바꾸는 트리거를 함께 적어주세요."
        )
    if gap.kind == "workflow":
        return (
            f"'{subject}'가 실제 환경에서 작동하는 장면을 5단계 이내로 풀어주세요. "
            "'누가 → 무엇을 보고 → 어떤 행동을 → 어떤 결과를 만든다'까지 명시해주세요."
        )
    if gap.kind == "relation":
        return (
            "이미 말씀하신 핵심 개념들 사이에서 가장 중요한 인과/선행/포함 관계는 무엇인가요? "
            "'A가 B를 발생시킨다' 또는 'C는 D의 한 종류다' 형태로 한 줄 적어주세요."
        )
    if gap.kind == "excluded_meaning":
        return (
            f"'{subject}'에서 사람들이 흔히 오해하는 의미가 있나요? "
            "'OO처럼 들리지만 실제로는 OO가 아니다'를 한 문장으로 적어주세요."
        )
    if gap.kind == "constraint":
        return (
            "이 아이디어를 1차로 검증할 때 절대 넘으면 안 되는 제약(예산/규제/시간/데이터)은 "
            "무엇인가요? 가장 단단한 제약 1개와 그 이유를 적어주세요."
        )
    if gap.kind == "evidence_boundary":
        return (
            "이 리서치 결과물에 절대 포함되면 안 되는 근거 종류가 있나요? "
            "예: 추정치 only, 광고성 블로그, 단일 사례, 5년 이상 묵은 통계. "
            "채택 가능 한도와 그 이유도 같이 적어주세요."
        )
    if gap.kind == "trigger":
        return (
            f"'{subject}' 환경에서 actor가 행동을 시작하게 만드는 신호/사건은 무엇인가요? "
            "관찰 가능한 트리거 1-2개를 적어주세요."
        )
    return (
        f"'{subject}'에 대해 사용자가 가진 질문 중 정의가 가장 흔들리는 용어 한 개를 골라주세요."
    )


def _candidate_interpretations(*, topic: str) -> tuple[CandidateInterpretation, ...]:
    """Return candidate interpretations of a topic.

    Heuristic stub: returns empty by default. The LLM-backed counselling layer
    should override with grounded interpretations. Tests assert the field is
    addressable, not its content.
    """
    del topic  # used by future LLM-backed override
    return ()


def _contrast_probes(gap: OntologyGap) -> tuple[Mapping[str, str], ...]:
    """Optional 2-3 concrete contrast probes the UI can render under the question."""
    if gap.kind == "entity":
        return (
            {"label": "물리적 대상", "description": "장비/소재/생물 같은 실체"},
            {"label": "데이터/정보 대상", "description": "측정값/문서/이벤트 같은 정보"},
            {"label": "관계/프로세스", "description": "결과로서의 흐름/의사결정"},
        )
    if gap.kind == "excluded_meaning":
        return (
            {"label": "명백히 아닌 영역", "description": "오해를 초래할 수 있는 인접 분야"},
            {"label": "지금은 미루는 영역", "description": "관련 있지만 1차 범위 밖"},
        )
    return ()
