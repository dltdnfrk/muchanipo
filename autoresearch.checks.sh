#!/usr/bin/env bash
# Backpressure checks for kept autoresearch changes.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")" && pwd)
cd "$ROOT"

python3 -m pytest \
  tests/test_pipeline_runner.py \
  tests/test_muchanipo_terminal.py \
  tests/test_e2e_tauri_smoke.py \
  tests/test_execution_real_wire.py \
  tests/test_model_router_config.py \
  tests/test_model_gateway_routing.py \
  tests/test_provider_kimi.py \
  tests/test_provider_gemini.py \
  tests/test_provider_codex.py \
  -q

npm --prefix app/muchanipo-tauri run build

(
  cd app/muchanipo-tauri
  cargo test
  cargo fmt --check
)
