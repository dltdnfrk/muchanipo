# Third Party Notices

This file records third-party material that is bundled, sampled, adapted, or
license-sensitive in Muchanipo. Pure reference inspiration is tracked in
`docs/reference-implementation-inventory.md`.

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
  contains selected local pattern ports/adapters around search, council, and
  ReACT-style report planning.
- Compliance note: do not copy additional MiroFish code, prompts, schemas, or
  report templates into Muchanipo without a dedicated AGPL compliance review.

## GBrain

- Source: https://github.com/garrytan/gbrain
- License note: project documentation has referenced Apache-2.0, while a pinned
  GitHub license check may report MIT for some revisions. Verify the exact
  source revision before copying additional material.
- Local status: Muchanipo uses local GBrain-style compiled-truth, timeline,
  vault-routing, and wiki persistence patterns.

## MIT / Permissive Reference Projects

Karpathy Autoresearch and GPTaku/show-me-the-prd are tracked as permissive or
reference-only projects in the runtime inventory. They should stay there unless
source code, prompts, schemas, or assets are copied into this repo. If copied,
add the exact source URL, revision, license, and modification note here.

## License Verification Required

MemPalace and OASIS/CAMEL-AI are not cleared under this permissive bucket. The
runtime inventory currently treats MemPalace as `unknown` and OASIS/CAMEL-AI as
`Apache-2.0 or project-specific; verify upstream component before copying code`.
Do not copy additional source code, prompts, schemas, or assets from those
projects until the exact upstream source URL, revision, and license are recorded.
