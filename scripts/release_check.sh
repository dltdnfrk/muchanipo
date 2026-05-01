#!/usr/bin/env bash
# Release-prep verification for the terminal-first Muchanipo CLI.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
PYTHON_BIN="${PYTHON_BIN:-python3}"
PYTHON311_BIN="${PYTHON311_BIN:-python3.11}"
TMP_ROOT="${TMPDIR:-/tmp}/muchanipo-release-check-$(date +%Y%m%dT%H%M%S)"

cd "$ROOT"
mkdir -p "$TMP_ROOT"

echo "[release] generated artifact hygiene"
if git status --short -- build dist '*.egg-info' | grep -q .; then
  echo "[release] FAIL: generated release artifacts are present in the repo root"
  git status --short -- build dist '*.egg-info'
  exit 1
fi

echo "[release] focused orchestration tests"
"$PYTHON_BIN" -m pytest tests/test_orchestration.py -q

echo "[release] CLI/TUI tests"
"$PYTHON_BIN" -m pytest tests/test_muchanipo_server.py tests/test_muchanipo_terminal.py -q

echo "[release] full Python tests"
"$PYTHON_BIN" -m pytest -q

echo "[release] diff hygiene"
git diff --check

echo "[release] orchestration status"
"$PYTHON_BIN" -m muchanipo orchestrate --session "${MUCHANIPO_TMUX_SESSION:-muni}" --json >/dev/null

echo "[release] orchestration cleanup dry-run"
"$PYTHON_BIN" -m muchanipo orchestrate \
  --session "${MUCHANIPO_TMUX_SESSION:-muni}" \
  --cleanup-workers \
  --dry-run \
  --json >/dev/null

echo "[release] contracts"
"$PYTHON_BIN" -m muchanipo contracts --json >/dev/null

echo "[release] offline demo"
"$PYTHON_BIN" -m muchanipo demo --run-dir "$TMP_ROOT/demo" --plain >/dev/null

if command -v "$PYTHON311_BIN" >/dev/null 2>&1; then
  echo "[release] wheel build"
  SOURCE_COPY="$TMP_ROOT/source"
  mkdir -p "$SOURCE_COPY"
  tar \
    --exclude .git \
    --exclude .pytest_cache \
    --exclude build \
    --exclude dist \
    --exclude '*.egg-info' \
    --exclude __pycache__ \
    -cf - . | tar -xf - -C "$SOURCE_COPY"
  "$PYTHON311_BIN" -m pip wheel --no-deps "$SOURCE_COPY" -w "$TMP_ROOT/dist" >/dev/null
  WHEEL_PATH=$(find "$TMP_ROOT/dist" -name 'muchanipo-*.whl' -print -quit)
  if [[ -z "$WHEEL_PATH" ]]; then
    echo "[release] FAIL: wheel was not produced"
    exit 1
  fi
  echo "[release] installed wheel smoke"
  "$PYTHON311_BIN" -m venv "$TMP_ROOT/venv"
  "$TMP_ROOT/venv/bin/python" -m pip install --no-deps "$WHEEL_PATH" >/dev/null
  "$TMP_ROOT/venv/bin/muchanipo" contracts --json >/dev/null
  "$TMP_ROOT/venv/bin/python" -m muchanipo contracts --json >/dev/null
else
  echo "[release] skip wheel build: $PYTHON311_BIN not found"
fi

if git status --short -- build dist '*.egg-info' | grep -q .; then
  echo "[release] FAIL: release check left generated artifacts in the repo root"
  git status --short -- build dist '*.egg-info'
  exit 1
fi

echo "[release] PASS"
echo "[release] artifacts: $TMP_ROOT"
