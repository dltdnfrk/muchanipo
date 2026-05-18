# Third Party Notices

This file records third-party material that is bundled, sampled, adapted, or
license-sensitive in Muchanipo. Pure reference inspiration is tracked in
`docs/reference-implementation-inventory.md`.

Current S0 audit status: the GOALS reference stack has no unexplained
stage-level overclaim in `python -m muchanipo references --json`. This notice
file covers the bundled, sampled, adapted, or license-sensitive entries below;
clean-room/non-bundled entries are explicitly called out so they are not treated
as hidden vendored dependencies.

## Nemotron-Personas-Korea

- Source: https://huggingface.co/datasets/nvidia/Nemotron-Personas-Korea
- License: CC-BY-4.0
- Local material: `vault/personas/seeds/korea/agtech-farmers-sample500.jsonl`
- Use: filtered/sample seed data for Korean agtech/farmer persona grounding.
- Modification note: local sample is selected for Muchanipo persona generation
  tests and runtime seed behavior; preserve dataset provenance in downstream
  outputs.
- Attribution note: external reports or redistributed artifacts that depend on
  this data should include CC-BY-4.0 attribution and mark filtered/sampled use.

## MiroFish

- Source: https://github.com/666ghj/MiroFish
- Documented license: AGPL-3.0
- Local status: no full upstream repository is vendored. Muchanipo currently
  contains selected local runtime ports/adapters around search, council,
  MiroFish-style swarm simulation records, and ReACT-style report planning.
- Runtime note: stage 5 uses these selected local ports/adapters for real
  ontology-derived persona generation, world graph construction, agent
  environment setup, council simulation events, transcript/deep-interaction
  surfaces, search, and report planning behavior.
- Compliance note: preserve notices for copied/adapted material, and do not
  copy additional MiroFish code, prompts, schemas, or report templates into
  Muchanipo without a dedicated AGPL compliance review.

## GBrain

- Source: https://github.com/garrytan/gbrain
- License: MIT as verified from the upstream `LICENSE` file during the
  2026-05-02 audit clone.
- Local status: Muchanipo uses a clean-room local GBrain runtime adaptation:
  compiled truth, append-only event ledger, timeline, typed links, brain-first
  lookup route, vault routing, and wiki persistence patterns.
- Compliance note: if future work copies upstream TypeScript source instead of
  using the local Python adaptation, preserve the MIT copyright and permission
  notice in the copied material.

## GPTaku show-me-the-prd

- Source: https://github.com/fivetaku/show-me-the-prd
- Marketplace/source family: https://github.com/fivetaku/gptaku_plugins
- Pinned revision: `7b22b070a685115a8687ea95fb95d398e4daf043`
- License: MIT as declared by upstream plugin metadata and README.
- Local material: `third_party/show-me-the-prd/`, including the plugin
  manifest, command prompt, skill instructions, interview guide, research
  strategy, and document templates.
- Runtime use: `src/interview/show_me_the_prd_port.py` exposes the upstream
  PRD interview workflow as Muchanipo Stage 1 runtime evidence.
- Modification note: the local Python port is not a full Claude/GPTaku runtime;
  it preserves the upstream workflow contract and records whether user answers
  or synthetic OfficeHours fills drove the generated PRD artifacts.
- Compliance boundary: the pinned upstream repository does not ship a standalone
  `LICENSE` file. Preserve the upstream README/plugin metadata with this vendored
  material, and do not distribute release artifacts containing
  `third_party/show-me-the-prd` until a complete upstream license notice is
  added or the vendored prompt material is excluded from that artifact.

## Plannotator

- Source: https://github.com/backnotprop/plannotator
- Pinned revision: `6324a0c859f06030b47d71c02b7c6fed09fa0b92`
- License: MIT OR Apache-2.0
- Local material: `third_party/plannotator/`, including upstream package
  metadata, licenses, editor/UI source, parser/types, and feedback templates.
- Runtime use: `app/muchanipo-tauri/src/plannotator-port/` copies the
  browser-safe parser/types/feedback contract, and
  `app/muchanipo-tauri/src/components/PlannotatorPlanEditor.tsx` embeds the
  plan annotation flow inside the Muchanipo Tauri plan HITL gate.
- Modification note: Muchanipo does not launch the upstream Plannotator web app
  as a separate surface; it ports the block/annotation/export model into a
  constrained in-app plan editor and submits Plannotator-style annotations to
  the pipeline before targeting.
- Security boundary: the vendored upstream workspace and lockfile are source
  evidence only. Do not install, build, package, or execute
  `third_party/plannotator` as production application code without a fresh
  dependency audit. The Tauri product uses the constrained port under
  `app/muchanipo-tauri/src/plannotator-port/` instead.

## Karpathy Autoresearch

- Source: https://github.com/karpathy/autoresearch
- Pinned revision: `228791fb499afffb54b46200aca536f79142f117`
- License declaration: MIT as declared by the upstream `README.md`.
- Local material: `third_party/karpathy-autoresearch/`, including upstream
  README, `program.md`, `prepare.py`, `train.py`, analysis notebook, project
  metadata, and lockfile.
- Runtime use: `src/research/karpathy_autoresearch.py` ports the upstream
  experiment loop into Muchanipo Stage 3 source research. The local runner
  writes a `program.md`, `results.tsv`, and per-iteration artifacts, evaluates
  a fixed lower-is-better source-grounding metric, keeps strict improvements,
  and discards non-improvements.
- Modification note: upstream edits `train.py`, runs fixed-time GPU training,
  and uses git keep/reset around `val_bpb`. Muchanipo adapts the single mutable
  experiment surface to `ResearchPlan.queries` and uses scratch-run retention
  instead of resetting the user's repository.
- Compliance boundary: the pinned upstream tree in this snapshot declares MIT
  in `README.md` but does not include a standalone `LICENSE` file. Preserve
  `third_party/karpathy-autoresearch/UPSTREAM.md` with copied material and run
  release packaging review before external redistribution.

## Clean-room / non-bundled reference statuses

These entries are part of the S0 reference inventory but do not currently add
bundled upstream source or sampled external data to the product artifact:

- Google Gemini Deep Research Max: clean-room runtime contract only. Muchanipo
  records observed async/cost/token/HITL behavior and does not call or copy
  Google's private runtime.
- HACHIMI: clean-room persona-generation controls in local Python. No upstream
  HACHIMI corpus, provider pool, Streamlit UI, prompts, schemas, or code are
  bundled.
- MAP-Elites / EvoAgentX: clean-room algorithmic diversity-map adaptation. No
  EvoAgentX source is bundled.
- OASIS / CAMEL-AI: clean-room local council protocol. The inventory records the
  upstream component as `Apache-2.0 or project-specific; verify upstream
  component before copying code`; no upstream runtime is bundled.
- MemPalace: clean-room local stdlib memory-room/wing index and persistence
  behavior. No upstream MemPalace source is bundled.

## License Verification Required

OASIS/CAMEL-AI remains outside the permissive-copy bucket until the exact
upstream component URL, revision, and license are recorded for any future copied
code, prompts, schemas, or assets. MemPalace is currently treated as a clean-room
local implementation; add a dedicated notice before copying upstream source.
