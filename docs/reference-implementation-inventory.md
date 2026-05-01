# External Project Integration Inventory

This inventory separates real Muchanipo runtime integrations from gaps that
still need direct ports, adapters, vendoring decisions, or license review.

Use the machine-readable runtime view for the current source of truth:

```bash
muchanipo references --json
```

## Classification Rules

- `concept only`: not acceptable as a final product claim; use only as a
  temporary gap label until a real integration lands or the project is removed
  from the stage contract.
- `clean-room implementation`: local Muchanipo code implements the behavior
  without vendoring upstream source.
- `partial port`: selected local code follows or adapts a reference pattern;
  verify license boundaries before expanding.
- `vendored code`: upstream source is bundled in this repo.
- `external runtime/API`: local adapter calls a provider, API, service, or CLI.
- `dataset`: local or external data asset used by runtime behavior.

## Current Position

The product standard is real behavior, not decorative reference. The repo does
not claim that every upstream project is fully vendored, but every stage-level
project claim must map to a local runtime module, adapter, dataset, executable
port, or an explicit gap.

High-risk boundary:

- `MiroFish` is documented as AGPL-3.0. Treat current behavior as a real local
  port/adaptation of ontology-derived persona profiles and round orchestration;
  do not vendor more upstream source unless a dedicated compliance review
  approves it.

Dataset boundary:

- `Nemotron-Personas-Korea` is CC-BY-4.0. Preserve attribution and mark local
  samples/filtered use when personas or outputs depend on it.

Known gaps are intentionally surfaced by `muchanipo references` instead of
being hidden behind broad "implemented" labels.

The JSON report separates `implemented` from `ready`: `implemented` only means
the referenced code path exists, while `ready=false` and `claim_level` explain
why a stage cannot be marketed as full parity yet.

Stage 2 HITL gates now distinguish reviewed approval from synthetic approval:
`auto_approve` and Plannotator offline fallback set `synthetic=true`, pipeline
artifacts expose `*_gate_synthetic`, and live mode rejects synthetic HITL gates.

Stage 1 intake now runs the local show-me-the-prd question selector before
ResearchBrief creation. Pipeline artifacts record the question count and rubric
dimension order so fixed answer injection cannot masquerade as an adaptive loop.

Stage 2 targeting now records the actual academic sources used and can fall
back from OpenAlex seed papers to the six-source academic sync adapter when
live academic targeting is enabled.

Stage 4 evidence grounding now fails closed on basic source structure before
trusting optional lockdown integration: quotes must be grounded in source text,
source locators and DOI metadata must be structurally valid, and A-grade
academic evidence from OpenAlex/Crossref/Semantic Scholar/Unpaywall/CORE must
preserve DOI provenance when available.

Stage 3 research artifacts now distinguish runner existence from actual backend
execution. `research_backend_trace`, `research_backend_kinds`, and
`research_evidence_kinds` record what ran, and `research_memory_store` is set to
`not_executed` unless the vault/InsightForge memory adapter actually runs or
produces memory-backed evidence.

Deep Research Max observations are now represented as a local autoresearch
runtime contract, not as a claim to private Google implementation parity.
`depth=max` records a background-async execution mode, phase trace template,
stream event contract, stale-job timeout, client timeout, and token ledger
fields including tool-use and thought tokens. The observed Max probe usage
(`699116` total tokens, including `618481` tool-use tokens and `64413` thought
tokens) is surfaced as calibration metadata so local runs must budget for
agentic retrieval cost instead of counting visible report tokens only.

Stage 6 ReACT now executes a local Think/Act/Observe/Write loop before report
appendices are rendered. The executor parses `<tool_call>` payloads, calls the
local InsightForge and MemPalace backends when they are available, and writes
`section_markdown` from the resulting final answer. External web search is not
wired into the offline executor and remains a surfaced readiness gap.

## Verification

Inventory and readiness are tested by:

```bash
python3 -m pytest tests/test_stage_reference_contracts.py tests/test_muchanipo_terminal.py
```
