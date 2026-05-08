# Deep Interview Ontology Execution Layer Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Turn Muchanipo intake from a PRD/questionnaire form into an LLM-guided Deep Interview loop that discovers ontology, uncertainty, and execution/capability structure before research execution.

**Architecture:** Use Manyfast only as a flow reference: idea intake -> AI questionnaire -> chat refinement -> PRD/map/spec generation. Do not copy PRD wording. Muchanipo should instead run an ontology-first counselling loop: detect what the model does not know, ask one high-leverage Socratic question, update an explicit ontology state, and only then build research goals/capability graph/execution plan.

**Tech Stack:** Python backend (`src/interview`, `src/intent`, `src/muchanipo/server.py`), Tauri React UI (`app/muchanipo-tauri/src/pages/RunProgress.tsx`, `src/components/InterviewQuestion.tsx`), event stream JSON lines, pytest, npm build, cargo tests.

---

## Reference Findings

### Manyfast editor page

Direct browser access to the shared URL was attempted. The page stayed on `에디터를 불러오고 있습니다 / 잠시만 기다려 주세요.` because this browser session is unauthenticated.

Observed API status from browser fetch:

- `/auth/proxy/session` -> `200 {"user":null}`
- document/thread/model endpoints -> `401 Unauthorized`

So the live document content could not be inspected directly from this unauthenticated session.

However, the loaded frontend bundle reveals the product flow:

- project starts through `질문지로 시작하기`, `자료에서 내용 추출하기`, or `빈 프로젝트`
- AI assistant Manny says it will ask six questions to clarify scope/target
- after answers, it generates a PRD draft
- user can continue in chat: review PRD, detail requirements, add feature
- maps/views include `prdMap`, `featureMap`, `userFlowMap`, `wireframeMap`
- PRD changes can sync to feature spec
- planning and execution modes exist in chat copy: Plan Mode refines plans before agreement; Execute Mode works quickly with step previews

Takeaway: borrow the **flow skeleton** only:

```text
idea/materials
-> AI asks ambiguity-reducing questions
-> user answers in chat
-> AI builds structured map/document
-> user continues refinement
-> map/spec/execution artifacts update
```

Do not borrow the fixed six-question PRD form.

### BeSir / ServerKit concept to adopt

The user-provided article describes the missing product architecture more precisely:

```text
BeSir Studio = AI design space
  -> semantic structure / Ontology
  -> execution structure / Capability Graph

BeSir Browser = execution interface
  -> AI as actual system user
  -> natural language requests become actions/reports/dashboards

Key loop:
  interviews are ingested
  AI detects what is still ambiguous
  AI generates concrete follow-up questions
  answers repeat for several rounds
  ontology becomes complete enough to execute
```

Muchanipo equivalent:

```text
Muchanipo Goals/Studio layer
  -> Deep Interview extracts ontology
  -> uncertainty questions reduce ambiguity
  -> ontology graph + capability/research graph are built

Muchanipo Browser/Workspace layer
  -> user sees live goals, assumptions, evidence gaps, agent activity
  -> AI executes source-backed research/council/persona/report pipeline
```

---

## Target Flow

```text
1. Seed Goal
   User enters rough topic or problem statement.

2. Ontology Seed
   System extracts provisional entities, actors, actions, triggers, signals,
   states, constraints, evidence types, excluded meanings.

3. Unknown Detection
   System computes what it cannot safely infer:
   ambiguous terms, overloaded segments, missing actor, missing workflow,
   weak evidence boundary, competing interpretation.

4. Socratic Question
   LLM asks exactly one high-leverage follow-up question.
   It may include contrast probes, but not fixed PRD fields.

5. Answer Assimilation
   User answer updates ontology state and coverage/entropy.

6. Repeat Until Gate
   Continue until ontology coverage threshold and evidence boundary threshold pass.

7. Capability / Execution Graph
   Convert ontology into research goals, source search facets, council roles,
   persona sampling constraints, and final report sections.

8. Live Execution Workspace
   UI shows: current goal, ontology map, open unknowns, latest question,
   answer history, execution graph, evidence state, pipeline heartbeat.
```

---

## Data Model

### Task 1: Add ontology state types

**Objective:** Represent the interview as evolving ontology, not a list of PRD answers.

**Files:**
- Create/modify: `src/interview/ontology_state.py`
- Test: `tests/test_interview_ontology_state.py`

**Model:**

```python
from dataclasses import dataclass, field

@dataclass
class OntologyEntity:
    id: str
    label: str
    kind: str  # actor | object | system | event | signal | state | constraint | evidence
    description: str = ""
    confidence: float = 0.0
    source_turn_ids: list[str] = field(default_factory=list)

@dataclass
class OntologyRelation:
    source: str
    predicate: str  # uses | triggers | observes | pays_for | decides | blocks | evidences
    target: str
    confidence: float = 0.0
    source_turn_ids: list[str] = field(default_factory=list)

@dataclass
class UnknownSlot:
    id: str
    kind: str  # ambiguous_term | missing_actor | missing_workflow | evidence_gap | boundary_gap
    label: str
    why_it_matters: str
    candidate_interpretations: list[str] = field(default_factory=list)
    entropy: float = 1.0

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
```

**Verification:**

```bash
python -m pytest tests/test_interview_ontology_state.py -q
```

Expected: ontology state can serialize to/from JSON and preserve unknown entropy ordering.

---

### Task 2: Replace nominal Q1-Q6 progression with unknown-first routing

**Objective:** Keep old IDs only for compatibility, but choose next question by highest-value unknown.

**Files:**
- Modify: `src/intent/interview_rubric.py`
- Modify: `src/interview/counselling.py`
- Test: `tests/test_prd_counselling.py`
- Test: `tests/test_interview_rubric.py`

**Rules:**

```text
next question priority:
1. ambiguous core noun blocks ontology root
2. missing actor/decision/user segment blocks workflow
3. missing trigger/signal/action blocks causal chain
4. missing boundary/excluded meaning risks category drift
5. missing evidence boundary risks ungrounded research
6. optional document/output details only after ontology is stable
```

**Verification:**

```bash
python -m pytest tests/test_prd_counselling.py tests/test_interview_rubric.py -q
```

Expected:
- no generic `what decision will you make` wording
- high-entropy unknown is selected before fixed Q order
- document/PRD/output questions do not appear before ontology coverage gate

---

### Task 3: Add LLM prompt contract for `identify_unknowns`

**Objective:** Split the LLM task into two explicit operations: extract ontology and ask next question.

**Files:**
- Modify: `src/interview/counselling.py`
- Test: `tests/test_prd_counselling.py`

**Prompt contract:**

```json
{
  "ontology_delta": {
    "entities": [],
    "relations": [],
    "excluded_meanings": [],
    "evidence_boundaries": []
  },
  "unknowns": [
    {
      "kind": "ambiguous_term",
      "label": "재택의료",
      "why_it_matters": "시장/규제/사용자 workflow가 달라짐",
      "candidate_interpretations": ["방문진료", "원격모니터링", "복약관리", "응급감지"],
      "entropy": 0.92
    }
  ],
  "next_question": {
    "question": "...",
    "rationale": "...",
    "targets_unknown_ids": ["..."]
  }
}
```

**Verification:**

```bash
python -m pytest tests/test_prd_counselling.py -q
```

Expected: fake gateway output updates ontology metadata and framed question includes `targets_unknown_ids`.

---

### Task 4: Emit ontology interview events to Tauri

**Objective:** Make UI show what the interview is discovering, not just a question textarea.

**Files:**
- Modify: `src/muchanipo/server.py`
- Modify: `src/muchanipo/events.py`
- Modify: `app/muchanipo-tauri/src/lib/types.ts`
- Test: `tests/test_tauri_event_contract.py`

**Event examples:**

```json
{"type":"interview.ontology.delta","entities":[...],"relations":[...],"unknowns":[...]}
{"type":"interview.question","question":"...","targets_unknown_ids":[...],"mode":"llm_counselling"}
{"type":"interview.coverage","coverage":0.58,"open_unknown_count":4}
```

**Verification:**

```bash
python -m pytest tests/test_tauri_event_contract.py -q
```

Expected: server emits `interview.ontology.delta` before or with each adaptive question.

---

### Task 5: Redesign Tauri interview UI around ontology discovery

**Objective:** The user should see a Deep Interview workspace, not questionnaire cards.

**Files:**
- Modify: `app/muchanipo-tauri/src/pages/RunProgress.tsx`
- Modify: `app/muchanipo-tauri/src/components/InterviewQuestion.tsx`
- Modify: `app/muchanipo-tauri/src/index.css`

**UI layout:**

```text
Left: current Socratic question + textarea answer
Center: ontology map / unknowns board
Right: evidence boundary + execution graph preview
Bottom: live activity timeline / heartbeat
```

**Question card copy:**

```text
Deep Interview
지금 AI가 모르는 것: [재택의료의 범위] [결제/도입 주체] [신호->행동 workflow]
다음 질문은 이 모호성을 줄이기 위한 것입니다.
```

**Verification:**

```bash
cd app/muchanipo-tauri && npm run build
```

Expected: build passes and UI no longer exposes fixed Q1-Q6/questionnaire labels to the user.

---

### Task 6: Add capability/execution graph compiler

**Objective:** Convert stabilized ontology into the execution graph that powers source-backed research.

**Files:**
- Create: `src/interview/capability_graph.py`
- Modify: `src/pipeline/idea_to_council.py`
- Test: `tests/test_interview_capability_graph.py`

**Graph nodes:**

```text
ResearchFacet(entity/relation/evidence_gap)
SourceRequirement(source_type, geography, freshness, trust_level)
CouncilRole(actor/evidence boundary)
PersonaConstraint(user segment / excluded meaning)
ReportSection(ontology-backed section)
```

**Verification:**

```bash
python -m pytest tests/test_interview_capability_graph.py tests/test_pipeline_runner.py -q
```

Expected: capability graph includes search facets and evidence boundaries derived from ontology state.

---

### Task 7: Goals mode acceptance test

**Objective:** Prove the full goals-mode loop works for a vague topic.

**Files:**
- Create/modify: `tests/test_goals_mode_deep_interview.py`

**Scenario:**

Topic:

```text
한국 65세 이상 1인 가구 재택의료 SaaS
```

Expected first questions should ask about:

- what `재택의료` includes/excludes
- who the actual actor/decision maker is
- which workflow/event is being optimized
- what evidence would distinguish valid vs invalid interpretations

Expected first questions should not ask:

- `답을 얻은 뒤 실제로 어떤 결정을 내릴 건가요?`
- `PRD가 왜 실행 불가능한지?`
- generic output format questions

**Verification:**

```bash
python -m pytest tests/test_goals_mode_deep_interview.py -q
```

---

### Task 8: Live Tauri screenshot verification

**Objective:** Final PASS requires real UI evidence.

**Files:**
- No code unless UI fails.

**Commands:**

```bash
cd app/muchanipo-tauri
VITE_MUCHANIPO_AUTOSTART_TOPIC='한국 65세 이상 1인 가구 재택의료 SaaS goals mode deep interview ontology extraction' \
  RUSTUP_TOOLCHAIN=stable npm run tauri dev
```

Capture the Muchanipo window and verify:

- dark workspace renders, not blank canvas
- current Socratic question is visible
- unknowns/ontology panel is visible
- live activity heartbeat is visible
- user can answer via textarea
- follow-up question changes based on answer

Expected evidence:

```text
screenshot path
run id
event log excerpt
pytest/build results
```

---

## Product Rules

1. Do not call the product feature `PRD interview` in user-visible UI.
2. User-visible label should be `Deep Interview`, `Ontology Discovery`, or `Goals Mode`.
3. Q1-Q6 IDs may remain internal only.
4. The LLM must ask one adaptive question at a time.
5. The question must target a named unknown/ambiguity.
6. The answer must update ontology state before moving on.
7. Execution must not start until ontology/evidence gates are satisfied or user explicitly overrides.
8. Final PASS requires screenshot + event evidence.

---

## Done Definition

- `python -m pytest tests/test_prd_counselling.py tests/test_interview_rubric.py tests/test_tauri_event_contract.py -q` passes.
- `cd app/muchanipo-tauri && npm run build` passes.
- Real Tauri window shows Deep Interview / ontology unknowns / live activity.
- Vague topic produces ontology questions, not PRD form questions.
- Capability graph connects interview ontology to source-backed research execution.
