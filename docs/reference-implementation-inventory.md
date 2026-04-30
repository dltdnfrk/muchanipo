# Reference Implementation Inventory

This inventory separates reference inspiration from code or data that is
actually present in Muchanipo.

Use the machine-readable runtime view for the current source of truth:

```bash
muchanipo references --json
```

## Classification Rules

- `concept only`: inspiration or workflow guidance only.
- `clean-room implementation`: local Muchanipo code implements the behavior
  without vendoring upstream source.
- `partial port`: selected local code follows or adapts a reference pattern;
  verify license boundaries before expanding.
- `vendored code`: upstream source is bundled in this repo.
- `external runtime/API`: local adapter calls a provider, API, service, or CLI.
- `dataset`: local or external data asset used by runtime behavior.

## Current Position

The repo does not claim that all upstream projects are fully vendored. The
six-stage runtime is backed by local modules, adapters, tests, and known gaps.

High-risk boundary:

- `MiroFish` is documented as AGPL-3.0. Treat it as a reference and partial
  local port only unless a dedicated compliance review approves vendoring.

Dataset boundary:

- `Nemotron-Personas-Korea` is CC-BY-4.0. Preserve attribution and mark local
  samples/filtered use when personas or outputs depend on it.

Known gaps are intentionally surfaced by `muchanipo references` instead of
being hidden behind broad "implemented" labels.

## Verification

Inventory and readiness are tested by:

```bash
python3 -m pytest tests/test_stage_reference_contracts.py tests/test_muchanipo_terminal.py
```
