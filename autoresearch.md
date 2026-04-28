# Autoresearch: Muchanipo App Completion Loop

## Objective
Drive Muchanipo toward a reliable local Tauri app that can run the full research pipeline, call local CLI providers, preserve progress across remounts, and render a final report without false failures.

## Metrics
- **Primary**: `quality_score` (points, higher is better) - composite pass score from backend smoke, frontend build, Rust bridge tests, and targeted provider/gateway tests.
- **Secondary**: `duration_seconds`, `failures`, `frontend_build`, `rust_tests`, `python_tests`.

## How to Run
`./autoresearch.sh` prints `METRIC name=value` lines.

For unattended monitoring:
`MAX_ITERATIONS=96 SLEEP_SECONDS=300 scripts/overnight_loop.sh`

## Files in Scope
- `app/muchanipo-tauri/src-tauri/src/python_bridge.rs` - Tauri bridge, CLI status/smoke/auth, event replay.
- `app/muchanipo-tauri/src/pages/*.tsx` - Settings, RunProgress, ReportView UX.
- `app/muchanipo-tauri/src/lib/*.ts` - Tauri client contracts and run index.
- `src/execution/**` - provider calls, model routing, gateway fallback, telemetry.
- `src/governance/**` - budget/cost/audit logging.
- `src/muchanipo/server.py` and `src/pipeline/**` - full pipeline event stream and backend smoke.
- `tests/**` - regression coverage for touched behavior.
- `scripts/**` - repeatable smoke/autoresearch runners.

## Off Limits
- Do not delete user runtime data under `vault/`, `raw/`, `.omc/`, `.omx/`, or `muchanipo-pipeline-*`.
- Do not remove installed CLI auth state.
- Do not add dependencies unless explicitly requested.
- Do not perform destructive git operations.

## Constraints
- Keep diffs small and commit with Lore protocol.
- Run frontend build, Rust tests, and relevant Python tests before claiming a keep.
- Treat provider stderr/noisy CLI output as diagnostic unless the subprocess exits non-zero.
- Preserve CLI mode as the default local execution path.
- Keep `/Applications/Muchanipo.app` as the canonical installed app; avoid duplicate app installs.

## What's Been Tried
- Stabilized GUI `.app` PATH and explicit CLI binary injection.
- Added Settings CLI status, smoke, and auth launch flows.
- Fixed report chunk replay duplication and abort sidebar cleanup.
- Separated non-fatal backend warnings from fatal errors so benign stderr no longer blocks report navigation.
- Added provider/model metadata to cost-log reservations and normalized provider model override telemetry.

## Current Backlog
- Add a manual/automated GUI full-run check for IdeaSubmit -> RunProgress -> ReportView.
- Harden packaged `.app` workspace resolution for repo-moved or clean-machine installs.
- Add secure API-key storage or avoid plaintext localStorage before wider distribution.
- Add explicit UI fallback when Terminal automation blocks `open_cli_auth`.
- Expand full pipeline HITL contract tests if interactive full mode becomes required.
