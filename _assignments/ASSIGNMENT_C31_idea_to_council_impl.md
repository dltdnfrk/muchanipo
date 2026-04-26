# C30 → C31 Implementation Plan — Idea-to-Council Pipeline Skeleton

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Replace the router-centered C30 implementation direction with an Idea-to-Council pipeline skeleton: idea dump → PRD-style brief → autoresearch → report → debate agents/mirofish → council.

**Architecture:** Top-level modules follow the user-facing lifecycle. Model routing is a support function under `src/execution/models.py`; budget/config/health/safety/audit live under `src/governance/`. Initial implementation should be stdlib-only and mock-first so the full test suite runs without API keys.

**Tech Stack:** Python stdlib dataclasses, pytest, existing muchanipo test conventions.

---

## Guardrails

1. Do **not** create top-level `src/router/`.
2. Do **not** delete `src/runtime/model-router.py` in this sprint.
3. New code must be API-key-free in tests via mock providers / mock evidence.
4. Keep files small and responsibility-focused.
5. Commit by lane, not as one huge commit.

---

## Task 1: Create pipeline stage and state contracts

**Objective:** Define the canonical lifecycle stages and serializable pipeline state.

**Files:**
- Create: `src/pipeline/__init__.py`
- Create: `src/pipeline/stages.py`
- Create: `src/pipeline/state.py`
- Test: `tests/test_pipeline_state.py`

**Implementation sketch:**

```python
# src/pipeline/stages.py
from enum import Enum

class Stage(str, Enum):
    IDEA_DUMP = "idea_dump"
    INTERVIEW = "interview"
    RESEARCH = "research"
    REPORT = "report"
    AGENTS = "agents"
    COUNCIL = "council"
    DONE = "done"
```

```python
# src/pipeline/state.py
from dataclasses import dataclass, field
from .stages import Stage

@dataclass
class PipelineState:
    run_id: str
    stage: Stage = Stage.IDEA_DUMP
    artifacts: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def advance(self, next_stage: Stage) -> "PipelineState":
        self.stage = next_stage
        return self
```

**Tests:**
- default stage is `IDEA_DUMP`
- `advance(Stage.INTERVIEW)` updates state
- artifacts can track `brief_id`, `report_id`, `council_id`

**Verify:**

```bash
python3 -m pytest tests/test_pipeline_state.py -q
```

---

## Task 2: Add intake IdeaDump

**Objective:** Preserve raw user input before any summarization or premature structure.

**Files:**
- Create: `src/intake/__init__.py`
- Create: `src/intake/idea_dump.py`
- Create: `src/intake/normalizer.py`
- Test: `tests/test_intake_idea_dump.py`

**Implementation sketch:**

```python
# src/intake/idea_dump.py
from dataclasses import dataclass, field
from datetime import datetime, timezone

@dataclass
class IdeaDump:
    raw_text: str
    source: str = "user"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    attachments: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if not self.raw_text.strip():
            raise ValueError("IdeaDump.raw_text must not be empty")
```

**Tests:**
- empty raw text raises
- attachments/tags default to separate lists
- normalizer keeps original semantic content

---

## Task 3: Add ResearchBrief contract

**Objective:** Represent the output of the PRD-style interview.

**Files:**
- Create: `src/interview/__init__.py`
- Create: `src/interview/brief.py`
- Test: `tests/test_research_brief.py`

**Implementation sketch:**

```python
# src/interview/brief.py
from dataclasses import dataclass, field

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

    @property
    def is_ready(self) -> bool:
        return bool(self.research_question.strip() and self.purpose.strip() and self.coverage_score >= 0.75)
```

**Tests:**
- brief with low coverage is not ready
- brief with question/purpose and coverage >= 0.75 is ready
- list fields do not share mutable defaults

---

## Task 4: Add interview session skeleton

**Objective:** Convert an IdeaDump into a partial ResearchBrief and identify missing PRD dimensions.

**Files:**
- Create: `src/interview/session.py`
- Create: `src/interview/rubric.py`
- Test: `tests/test_interview_session.py`

**Implementation sketch:**

```python
REQUIRED_DIMENSIONS = [
    "research_question",
    "purpose",
    "context",
    "deliverable_type",
    "quality_bar",
]
```

Acceptance:
- `InterviewSession.from_idea(idea)` starts at coverage 0.
- adding answers increases coverage.
- `to_brief()` creates ResearchBrief.

---

## Task 5: Add research plan and mock runner

**Objective:** Convert ResearchBrief into a mock ResearchPlan and mock findings.

**Files:**
- Create: `src/research/__init__.py`
- Create: `src/research/planner.py`
- Create: `src/research/runner.py`
- Create: `src/research/synthesis.py`
- Test: `tests/test_research_runner.py`

Acceptance:
- planner creates at least one query from `brief.research_question`.
- runner can return findings without network/API.
- findings keep evidence references.

---

## Task 6: Add evidence contracts and in-memory store

**Objective:** Preserve provenance and source quality for every finding.

**Files:**
- Create: `src/evidence/__init__.py`
- Create: `src/evidence/artifact.py`
- Create: `src/evidence/store.py`
- Create: `src/evidence/provenance.py`
- Create: `src/evidence/quality.py`
- Test: `tests/test_evidence_store.py`

Acceptance:
- EvidenceRef requires id and source grade.
- store can add/get/list refs.
- invalid source grade raises.

---

## Task 7: Add ResearchReport composer

**Objective:** Compose findings into a report artifact with limitations and open questions.

**Files:**
- Create: `src/report/__init__.py`
- Create: `src/report/schema.py`
- Create: `src/report/composer.py`
- Create: `src/report/templates/research_report.md`
- Test: `tests/test_report_composer.py`

Acceptance:
- report includes executive summary, findings, evidence, limitations.
- markdown output contains source ids.
- empty findings produce an explicit limitation warning.

---

## Task 8: Add DebateAgentSpec and mirofish generator

**Objective:** Generate debate agents from a ResearchReport, including mirofish.

**Files:**
- Create: `src/agents/__init__.py`
- Create: `src/agents/generator.py`
- Create: `src/agents/mirofish.py`
- Create: `src/agents/personas.py`
- Create: `src/agents/prompts.py`
- Test: `tests/test_agent_generator.py`

Acceptance:
- generated agents include `mirofish`.
- each agent has `source_report_id`.
- mirofish prompt explicitly asks for weak assumptions, missing evidence, counter-hypotheses, and next experiments.

---

## Task 9: Add council session skeleton

**Objective:** Run one mock council round using DebateAgentSpec objects.

**Files:**
- Create: `src/council/__init__.py`
- Create: `src/council/session.py`
- Create: `src/council/round.py`
- Create: `src/council/moderator.py`
- Create: `src/council/consensus.py`
- Test: `tests/test_council_session.py`

Acceptance:
- council session can run with mock responses.
- session records disagreements and next actions.
- no external model/API required.

---

## Task 10: Add execution model gateway mock

**Objective:** Provide a low-level execution adapter without making router the architecture boundary.

**Files:**
- Create: `src/execution/__init__.py`
- Create: `src/execution/runtime.py`
- Create: `src/execution/models.py`
- Create: `src/execution/providers/__init__.py`
- Create: `src/execution/providers/mock.py`
- Test: `tests/test_execution_models.py`

Acceptance:
- `ModelGateway.call(stage, prompt)` works with mock provider.
- no top-level `src/router/` exists.
- stage-specific policies are data, not hardcoded global defaults.

---

## Task 11: Add governance budget/audit skeleton

**Objective:** Track run-level cost and audit records across the entire pipeline.

**Files:**
- Create: `src/governance/__init__.py`
- Create: `src/governance/budget.py`
- Create: `src/governance/audit.py`
- Create: `src/governance/profiles.py`
- Test: `tests/test_governance_budget.py`

Acceptance:
- default profile resolution is `--profile > MUCHANIPO_PROFILE > dev` when wired.
- budget is run-level, not router-level.
- audit record includes stage, action, provider/model when available, estimate/actual cost.

---

## Task 12: Wire minimal end-to-end pipeline

**Objective:** Prove idea → brief → research → report → agents → council works with mocks.

**Files:**
- Create/Modify: `src/pipeline/idea_to_council.py`
- Test: `tests/test_idea_to_council_e2e.py`

Acceptance:
- a single raw idea string produces a CouncilSession.
- final state is `DONE`.
- artifacts include brief/report/agents/council ids or placeholders.
- test runs without API keys.

**Verify full suite:**

```bash
python3 -m pytest tests/ -q
```

---

## Suggested commit layout

```bash
git commit -m "feat(c31-a): add idea-to-brief pipeline skeleton"
git commit -m "feat(c31-b): add autoresearch and evidence skeleton"
git commit -m "feat(c31-c): add report and debate agent generation"
git commit -m "feat(c31-d): add council execution and governance skeleton"
git commit -m "test(c31): add mock e2e idea-to-council coverage"
```
