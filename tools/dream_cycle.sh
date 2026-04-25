#!/usr/bin/env bash
# Manual trigger for the muchanipo dream-cycle runner.
#
# Usage:
#   tools/dream_cycle.sh [--vault PATH] [--output-dir PATH] [--threshold N]
#                        [--scan-subdir NAME ...] [--no-write]
#
# Recommended cron schedule (KST):
#   0 3 * * *  cd /path/to/muchanipo && tools/dream_cycle.sh >> logs/dream-cycle.log 2>&1
#
# The script intentionally does not install crontab entries — operators are
# expected to wire it up themselves.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "[dream_cycle] $(date -u +%FT%TZ) repo=$REPO_ROOT python=$PYTHON_BIN"
"$PYTHON_BIN" -m src.dream.dream_runner "$@"
