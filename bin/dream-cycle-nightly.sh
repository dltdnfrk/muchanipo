#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

python3 - <<'PY'
from src.wiki.dream_cycle import DreamCycle

cycle = DreamCycle()
print(f"dream-cycle ready threshold={cycle.threshold} should_promote={cycle.should_promote()}")
PY
