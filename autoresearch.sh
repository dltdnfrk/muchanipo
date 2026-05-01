#!/usr/bin/env bash
# Composite Muchanipo quality benchmark for the local autoresearch loop.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")" && pwd)
LOG_DIR="$ROOT/.omc/autoresearch/logs"
mkdir -p "$LOG_DIR"

START_TS=$(python3 - <<'PY'
import time
print(time.time())
PY
)

score=0
failures=0
frontend_build=0
rust_tests=0
python_tests=0
depth_contract=0

run_step() {
  local name="$1"
  local var_name="$2"
  local points="$3"
  shift 3
  local log="$LOG_DIR/${name}.log"

  if "$@" >"$log" 2>&1; then
    score=$((score + points))
    printf -v "$var_name" '%s' 1
    printf 'METRIC %s=1\n' "$name"
  else
    failures=$((failures + 1))
    printf -v "$var_name" '%s' 0
    printf 'METRIC %s=0\n' "$name"
    printf '[autoresearch] %s failed; last 80 log lines:\n' "$name" >&2
    tail -80 "$log" >&2 || true
  fi
}

cd "$ROOT"

run_step python_tests python_tests 35 python3 -m pytest \
  tests/test_pipeline_runner.py \
  tests/test_e2e_tauri_smoke.py \
  tests/test_execution_real_wire.py \
  tests/test_model_router_config.py \
  tests/test_model_gateway_routing.py \
  tests/test_muchanipo_terminal.py \
  tests/test_provider_kimi.py \
  -q

run_step depth_contract depth_contract 5 python3 -m pytest \
  tests/test_pipeline_runner.py::test_run_pipeline_shallow_depth_reduces_internal_autoresearch_budget \
  tests/test_muchanipo_terminal.py::test_main_direct_topic_shortcut_accepts_depth_flag \
  tests/test_muchanipo_terminal.py::test_subprocess_demo_command_completes_offline \
  -q

run_step frontend_build frontend_build 30 npm --prefix app/muchanipo-tauri run build
run_step rust_tests rust_tests 30 bash -lc 'cd app/muchanipo-tauri && cargo test && cargo fmt --check'

END_TS=$(python3 - <<'PY'
import time
print(time.time())
PY
)
DURATION=$(python3 - "$START_TS" "$END_TS" <<'PY'
import sys
start = float(sys.argv[1])
end = float(sys.argv[2])
print(round(end - start, 3))
PY
)

printf 'METRIC quality_score=%s\n' "$score"
printf 'METRIC duration_seconds=%s\n' "$DURATION"
printf 'METRIC failures=%s\n' "$failures"
printf 'METRIC python_tests=%s\n' "$python_tests"
printf 'METRIC depth_contract=%s\n' "$depth_contract"
printf 'METRIC frontend_build=%s\n' "$frontend_build"
printf 'METRIC rust_tests=%s\n' "$rust_tests"

if [[ "$failures" -ne 0 ]]; then
  exit 1
fi
