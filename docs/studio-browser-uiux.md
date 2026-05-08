# Muchanipo Studio / Browser UIUX Split

## Thesis

Muchanipo should not feel like one long linear app that starts a topic and then keeps running. It should feel like two connected products:

```text
Muchanipo Studio  -> design / understanding / ontology construction
Muchanipo Browser -> execution / operation / evidence / artifacts
```

The split mirrors the BeSir framing the user referenced:

- Studio: where AI learns the user's domain, detects ambiguity, builds ontology, and designs the capability/execution graph.
- Browser: where AI acts as a real system user, executes the graph, gathers evidence, runs council/persona validation, and renders reports/dashboards.

## Why this matters

The product's core differentiator is not "it runs a research pipeline". The differentiator is:

```text
A frontier reasoning model conducts a professional Deep Interview,
figures out what it does not know,
asks ambiguity-reducing questions,
builds an ontology,
and only then executes research/council/report generation.
```

So the UI must make the distinction visible:

- Studio is deliberate, reflective, graph-building, high-reasoning.
- Browser is operational, live, source-backed, evidence-oriented.

## Information Architecture

### Top-level modes

```text
Studio
  ├─ Goal Intake
  ├─ Deep Interview
  ├─ Ontology Map
  ├─ Unknowns / Ambiguity Board
  ├─ Evidence Boundary
  └─ Capability / Execution Graph Designer

Browser
  ├─ Live Run
  ├─ Source Search
  ├─ Evidence Index
  ├─ Council Monitor
  ├─ Persona Validation
  ├─ Report / Dashboard
  └─ Vault / Export / Agent Trace
```

### Current route mapping

Current routes:

```text
/              -> IdeaSubmit
/run/:runId    -> RunProgress
/report/:runId -> ReportView
/settings      -> Settings
```

Proposed routes:

```text
/studio/new              -> Goal Intake
/studio/:goalId          -> Studio Workspace
/studio/:goalId/interview
/studio/:goalId/ontology
/studio/:goalId/graph

/browser/:runId          -> Browser Live Run
/browser/:runId/evidence
/browser/:runId/council
/browser/:runId/report
/settings
```

Backward-compatible aliases:

```text
/              -> /studio/new
/run/:runId    -> /browser/:runId
/report/:runId -> /browser/:runId/report
```

## Studio UX

### Studio purpose

Studio answers:

```text
What are we actually trying to understand?
What concepts are ambiguous?
What does the AI still not know?
What ontology must be stable before execution?
What capability graph should be executed?
```

### Studio primary screen

```text
┌──────────────── Sidebar ────────────────┬──────────────────────── Studio ───────────────────────┐
│ New Goal                                │ Deep Interview                                         │
│ Goals                                   │ ┌ Current question ──────────────────────────────────┐ │
│  • Strawberry diagnostics               │ │ The AI is reducing this ambiguity: 재택의료 범위     │ │
│  • Elderly home-care SaaS               │ │ Question: ...                                       │ │
│                                         │ │ [textarea answer]                                  │ │
│ Mode                                    │ └────────────────────────────────────────────────────┘ │
│  Studio                                 │                                                       │
│  Browser                                │ ┌ Unknowns Board ─────────────┐ ┌ Ontology Map ──────┐ │
│                                         │ │ ambiguous_term: 재택의료     │ │ Actor -> Signal     │ │
│                                         │ │ missing_actor: buyer         │ │ Signal -> Action    │ │
│                                         │ │ evidence_gap: reimbursement  │ │ Action -> Outcome   │ │
│                                         │ └─────────────────────────────┘ └────────────────────┘ │
│                                         │ ┌ Capability Graph Preview ───────────────────────────┐ │
│                                         │ │ search facets, source requirements, council roles    │ │
│                                         │ └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────┴───────────────────────────────────────────────────────┘
```

### Studio screen states

1. **Seed state**
   - User enters rough goal.
   - CTA: `Start Deep Interview`.
   - Copy: `Studio will first clarify ontology before execution.`

2. **Unknown detection state**
   - AI displays extracted unknowns.
   - Each unknown has kind, candidate interpretations, and why it matters.

3. **Question state**
   - One Socratic question.
   - Shows target unknown and expected answer shape.
   - Textarea-first; no questionnaire buttons by default.

4. **Assimilation state**
   - After answer, show `ontology_delta`:
     - new entity
     - narrowed definition
     - excluded meaning
     - new evidence boundary

5. **Graph-ready state**
   - Studio says ontology is sufficiently stable.
   - CTA: `Open in Browser` / `Execute Graph`.

## Browser UX

### Browser purpose

Browser answers:

```text
What is running right now?
Which sources were searched?
Which claims are supported?
What did council/persona agents say?
What report/dashboard artifact was produced?
```

### Browser primary screen

```text
┌────────────── Sidebar ───────────────┬──────────────────── Browser ─────────────────────────────┐
│ Runs                                 │ Live Execution                                           │
│  • run-abc executing                 │ ┌ Graph execution timeline ────────────────────────────┐ │
│  • run-def report ready              │ │ Interview ✓ Ontology ✓ Search → Evidence → Council    │ │
│                                      │ └──────────────────────────────────────────────────────┘ │
│ Views                                │ ┌ Current Activity ──────┐ ┌ Evidence Index ──────────┐ │
│  Live                                │ │ searching              │ │ Claim A: 3 sources       │ │
│  Evidence                            │ │ heartbeat received     │ │ Claim B: weak evidence   │ │
│  Council                             │ │ provider: opencode go  │ │ Claim C: needs review    │ │
│  Report                              │ └────────────────────────┘ └──────────────────────────┘ │
│                                      │ ┌ Council / Persona / Report panels ───────────────────┐ │
│                                      │ │ live turns, dissent, final synthesis                  │ │
│                                      │ └──────────────────────────────────────────────────────┘ │
└──────────────────────────────────────┴──────────────────────────────────────────────────────────┘
```

### Browser screen states

1. **Execution queued**
2. **Source search running**
3. **Evidence grading**
4. **Council deliberation**
5. **Persona validation**
6. **Report generation**
7. **Artifact ready**
8. **Blocked / needs Studio clarification**

Important: Browser can route back to Studio if evidence reveals unresolved ontology ambiguity.

```text
Browser found unresolved ambiguity: "clinic adoption" could mean hospital purchase or local government procurement.
CTA: Return to Studio to clarify.
```

## Event / Data Model

### Studio events

```json
{"type":"studio.goal.created","goal_id":"goal_...","topic":"..."}
{"type":"studio.unknowns.detected","unknowns":[...]}
{"type":"studio.question.emitted","question":"...","targets_unknown_ids":[...]}
{"type":"studio.answer.recorded","turn_id":"..."}
{"type":"studio.ontology.delta","entities":[...],"relations":[...],"excluded_meanings":[...]}
{"type":"studio.coverage.updated","coverage":0.72,"open_unknown_count":3}
{"type":"studio.graph.ready","capability_graph_id":"graph_..."}
```

### Browser events

```json
{"type":"browser.run.started","run_id":"run_...","graph_id":"graph_..."}
{"type":"browser.source.search.started","facet":"..."}
{"type":"browser.evidence.claim.updated","claim_id":"...","support":"strong|weak|missing"}
{"type":"browser.council.turn.started","role":"..."}
{"type":"browser.persona.validation.updated","segment":"..."}
{"type":"browser.report.section.ready","section_id":"..."}
{"type":"browser.run.blocked","reason":"ontology_ambiguity","return_to":"studio"}
{"type":"browser.run.done","report_id":"..."}
```

## Model Routing

Studio requires frontier reasoning:

```text
studio.unknown_detection      -> frontier model
studio.question_generation    -> frontier model
studio.answer_assimilation    -> frontier model
studio.ontology_gate          -> frontier model
studio.capability_graph       -> frontier or strong reasoning model
```

Browser can mix models:

```text
browser.status_summary        -> cheap/mini
browser.source_fetch          -> tool / deterministic
browser.evidence_grading      -> medium/frontier depending on claim
browser.council               -> frontier
browser.persona               -> frontier or specialist
browser.report_synthesis      -> frontier
```

## Implementation Steps

### Phase 1: Rename visible mental model

- `IdeaSubmit` becomes Studio entry.
- Add visible mode switch in `Sidebar`: `Studio` / `Browser`.
- Replace `새 리서치` with `새 Goal` or `New Goal` in Studio mode.
- Browser history still shows runs.

### Phase 2: Add Studio panels to existing RunProgress

Before route migration, use current `RunProgress` as bridge:

- top label: `STUDIO · Deep Interview` during interview
- show `Unknowns Board`
- show `Ontology Map` placeholder
- show `Execution Graph Preview`
- when pipeline starts, label switches to `BROWSER · Live Execution`

### Phase 3: Split routes

Add:

```tsx
<Route path="/studio/new" element={<IdeaSubmit />} />
<Route path="/studio/:goalId" element={<StudioWorkspace />} />
<Route path="/browser/:runId" element={<RunProgress />} />
```

Keep old aliases.

### Phase 4: Backend event split

Rename/add event namespaces:

- `interview.*` can remain internal.
- UI-facing should be `studio.*` and `browser.*`.

### Phase 5: Tauri verification

Final PASS requires screenshots:

- Studio screen with Deep Interview + Unknowns Board.
- Browser screen with execution timeline + evidence index.
- Return-to-Studio blocked state if ambiguity appears during execution.

## Design Principle

Studio should feel like:

```text
Cursor for understanding a problem domain.
```

Browser should feel like:

```text
Codex/Devin for watching AI execute a grounded plan.
```

## Craft / Copy Guardrails

The visual direction can stay dark, tool-like, and typographically calm, but the product must not feel like a generic AI-generated frontend. Treat copy, labels, and state changes as part of the interface contract.

### Human-made product feel

- Prefer stable nouns over marketing phrases: `Goal`, `Unknown`, `Evidence`, `Run`, `Report`.
- Avoid decorative AI language in chrome: do not overuse `AI`, `frontier`, `high reasoning`, `magic`, `auto`, or vague productivity claims in visible labels.
- Use short Korean UI copy for user-facing chrome; keep technical detail in secondary panels, tooltips, or logs.
- Keep copy consistent between states. A mode switch should not rewrite the whole screen in a way that feels like generated text changed beneath the user.
- Prefer domain-specific working language in the content area only when it came from the user's goal or backend event, not from a hardcoded vertical preset.

### Text stability / “글바뀜” rules

- Never rotate headline/subtitle copy automatically.
- Do not stream-rewrite headings while a backend step is running. Stream logs or evidence rows instead.
- Preserve layout width for status labels so `running → heartbeat → searching` does not cause visible jitter.
- Use skeleton rows or fixed-height event rows for loading; avoid replacing large blank cards with unrelated text blocks.
- If an LLM-generated question changes after assimilation, show it as a new turn, not as mutated text in place.

### Recommended chrome copy

```text
Studio                not “AI Studio”
Browser               not “AI Browser”
새 Goal               not “새 AI 리서치”
개념 정리             not “AI가 모호성을 제거합니다”
실행 준비             not “frontier model high reasoning”
근거 보기             not “source-backed evidence intelligence”
```

### Screen rule

Every screen should answer one quiet product question:

- Studio: `무엇을 더 정해야 실행할 수 있나?`
- Browser: `지금 무엇이 실행됐고, 어떤 근거가 남았나?`

If a sentence does not help answer one of those, remove it from the primary surface.
