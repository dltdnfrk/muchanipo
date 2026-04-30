# Muchanipo CLI JSON Contracts

Muchanipo exposes human-friendly terminal output by default and stable JSON for
agent/script inspection with `--json`.

Current schema version: `1`

Compatibility rule:

- Required top-level keys remain stable for a given `schema_version`.
- New additive fields may appear; consumers should ignore unknown fields.
- Breaking changes require a new `schema_version`.

Machine-readable contract metadata is available from:

```bash
muchanipo contracts --json
```

## `muchanipo doctor --json`

Required top-level keys:

- `schema_version`
- `command`
- `ok`
- `status`
- `runs_dir`
- `checks`
- `cli_statuses`
- `recommendations`

Purpose: inspect local readiness for the TUI-first CLI runtime.

## `muchanipo status --json`

Required top-level keys:

- `schema_version`
- `command`
- `providers`

Purpose: inspect installed/version status for provider CLIs.

## `muchanipo runs --json`

Required top-level keys:

- `schema_version`
- `command`
- `runs_dir`
- `limit`
- `runs`

Purpose: list recent terminal run summaries loaded from `summary.json`
artifacts.

## `muchanipo references --json`

Required top-level keys:

- `schema_version`
- `command`
- `stages`
- `references`
- `gaps`
- `license_warnings`

Purpose: inspect six-stage reference-project readiness, local runtime-backed
modules, known gaps, and license-sensitive boundaries.
