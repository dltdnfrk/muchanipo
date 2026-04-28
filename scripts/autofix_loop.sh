#!/usr/bin/env bash
# Unattended small-patch loop for Muchanipo.
#
# Safety contract:
# - starts each iteration only from a clean worktree
# - asks a Codex worker to make one bounded fix and commit it
# - independently runs backpressure checks after the worker returns
# - never uses reset/checkout/revert; failed dirty patches are stashed
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

MAX_ITERATIONS=${MAX_ITERATIONS:-24}
SLEEP_SECONDS=${SLEEP_SECONDS:-600}
RESULTS=${RESULTS:-"$ROOT/.omc/autoresearch/autofix-results.jsonl"}
SUMMARY=${SUMMARY:-"$ROOT/.omc/autoresearch/autofix-summary.md"}
LOG_DIR=${LOG_DIR:-"$ROOT/.omc/autoresearch/autofix-logs"}
CODEX_BIN=${CODEX_BIN:-codex}
PUSH_REMOTE=${PUSH_REMOTE:-origin}
PUSH_BRANCH=${PUSH_BRANCH:-$(git branch --show-current)}

mkdir -p "$LOG_DIR" "$(dirname "$RESULTS")"

json_append() {
  python3 - "$RESULTS" "$@" <<'PY'
import json
import pathlib
import sys
from datetime import datetime, timezone

path = pathlib.Path(sys.argv[1])
payload = json.loads(sys.argv[2])
payload.setdefault("logged_at", datetime.now(timezone.utc).isoformat())
with path.open("a", encoding="utf-8") as f:
    f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
PY
}

write_summary() {
  python3 - "$RESULTS" "$SUMMARY" <<'PY'
import json
import pathlib
import sys

results = pathlib.Path(sys.argv[1])
summary = pathlib.Path(sys.argv[2])
entries = []
if results.exists():
    for line in results.read_text(encoding="utf-8").splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue

committed = [e for e in entries if e.get("status") == "committed"]
failed = [e for e in entries if e.get("status") in {"failed", "stashed", "blocked"}]
lines = [
    "# Muchanipo Autofix Loop",
    "",
    f"- Iterations logged: {len(entries)}",
    f"- Committed: {len(committed)}",
    f"- Failed/blocked/stashed: {len(failed)}",
    "",
    "## Recent",
]
for entry in entries[-12:]:
    lines.append(
        f"- {entry.get('logged_at')} {entry.get('status')} "
        f"iteration={entry.get('iteration')} commit={entry.get('head_after', '')} "
        f"log={entry.get('log', '')}"
    )
summary.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
}

current_head() {
  git rev-parse --short HEAD
}

worktree_clean() {
  [[ -z "$(git status --short)" ]]
}

worker_prompt() {
  cat <<'PROMPT'
You are a bounded unattended Muchanipo autofix worker.

Mission:
- Improve the app by exactly one small, reviewable fix from the backlog in autoresearch.md or from obvious failing/weak test evidence.
- Prefer high-signal reliability issues: GUI full-run reliability, packaged app workspace resolution, API/CLI diagnostics, Settings/RunProgress/ReportView correctness, provider telemetry.

Hard rules:
- Start by reading autoresearch.md and git status.
- Do not use destructive git commands: no reset, checkout, restore, clean, revert, or rm of project/user data.
- Do not modify .omc, .omx, vault runtime data, installed CLI auth, or generated build outputs.
- No new dependencies.
- Keep the diff small.
- Add or update regression tests for the behavior you change when feasible.
- Run ./autoresearch.checks.sh before committing.
- If checks pass, commit with the repository Lore Commit Protocol.
- If checks fail and you cannot fix quickly, leave the worktree dirty and explain the blocker in your final message; the outer loop will stash it for review.

Output:
- Final message must include changed files, tests run, commit hash if committed, and remaining risk.
PROMPT
}

echo "[autofix] writing results to $RESULTS"
echo "[autofix] max iterations: $MAX_ITERATIONS, sleep: ${SLEEP_SECONDS}s"

for ((i = 1; i <= MAX_ITERATIONS; i++)); do
  log="$LOG_DIR/iteration-${i}.log"
  last_message="$LOG_DIR/iteration-${i}.final.txt"
  head_before=$(current_head)

  if ! worktree_clean; then
    status_json=$(python3 - <<'PY'
import json, subprocess
status = subprocess.check_output(["git", "status", "--short"], text=True)
print(json.dumps({"status": status}))
PY
)
    json_append "{\"iteration\": $i, \"status\": \"blocked\", \"head_before\": \"$head_before\", \"details\": $status_json, \"log\": \"$log\"}"
    write_summary
    echo "[autofix] blocked: worktree is dirty before iteration $i"
    exit 1
  fi

  echo "[autofix] iteration $i start: $head_before"
  status="failed"
  if worker_prompt | "$CODEX_BIN" exec --full-auto -C "$ROOT" -o "$last_message" - >"$log" 2>&1; then
    if ./autoresearch.checks.sh >>"$log" 2>&1; then
      if worktree_clean && [[ "$(current_head)" != "$head_before" ]]; then
        status="committed"
      elif worktree_clean; then
        status="no_change"
      else
        status="dirty_after_pass"
      fi
    else
      status="checks_failed"
    fi
  fi

  head_after=$(current_head)

  if [[ "$status" == "checks_failed" || "$status" == "failed" || "$status" == "dirty_after_pass" ]]; then
    if ! worktree_clean; then
      patch="$LOG_DIR/iteration-${i}.failed.patch"
      git diff --binary >"$patch" || true
      git status --short >"$LOG_DIR/iteration-${i}.failed-status.txt" || true
      git stash push -u -m "autofix iteration $i failed $(date -u +%Y-%m-%dT%H:%M:%SZ)" >>"$log" 2>&1 || true
      status="stashed"
    fi
  fi

  if [[ "$status" == "committed" ]]; then
    if git push "$PUSH_REMOTE" "HEAD:$PUSH_BRANCH" >>"$log" 2>&1; then
      status="pushed"
    else
      status="push_failed"
    fi
  fi

  json_append "{\"iteration\": $i, \"status\": \"$status\", \"head_before\": \"$head_before\", \"head_after\": \"$head_after\", \"log\": \"$log\", \"final_message\": \"$last_message\"}"
  write_summary
  echo "[autofix] iteration $i status=$status head=$head_after"

  if [[ "$status" == "blocked" ]]; then
    exit 1
  fi

  if [[ "$i" -lt "$MAX_ITERATIONS" ]]; then
    sleep "$SLEEP_SECONDS"
  fi
done
