#!/usr/bin/env bash
# Unattended small-patch loop for Muchanipo.
#
# Safety contract:
# - starts each iteration only from a clean worktree
# - asks Claude/Kimi peers for read-only review, then a Codex worker for one bounded fix
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
RUN_ID=${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}
CODEX_BIN=${CODEX_BIN:-codex}
CLAUDE_BIN=${CLAUDE_BIN:-claude}
KIMI_BIN=${KIMI_BIN:-kimi}
PEER_REVIEW=${PEER_REVIEW:-1}
PEER_TIMEOUT_SECONDS=${PEER_TIMEOUT_SECONDS:-600}
CLAUDE_TIMEOUT_SECONDS=${CLAUDE_TIMEOUT_SECONDS:-600}
KIMI_TIMEOUT_SECONDS=${KIMI_TIMEOUT_SECONDS:-600}
CLAUDE_MAX_BUDGET_USD=${CLAUDE_MAX_BUDGET_USD:-1.00}
NO_CHANGE_LIMIT=${NO_CHANGE_LIMIT:-3}
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

committed = [e for e in entries if e.get("status") in {"committed", "pushed"}]
failed = [
    e for e in entries
    if e.get("status") in {"failed", "stashed", "blocked", "checks_failed", "push_failed"}
]
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
  local peer_dir=${1:-}
  cat <<'PROMPT'
You are a bounded unattended Muchanipo autofix worker.

Mission:
- Improve the app by exactly one small, reviewable fix from the backlog in autoresearch.md or from obvious failing/weak test evidence.
- Prefer high-signal reliability issues: GUI full-run reliability, packaged app workspace resolution, API/CLI diagnostics, Settings/RunProgress/ReportView correctness, provider telemetry.
- If Claude and Kimi both say NO_CHANGE, only make a change when you can prove a small safe gap from local tests or code.

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

  if [[ -n "$peer_dir" ]]; then
    cat <<PROMPT

Peer review artifacts are advisory, not authoritative. Resolve contradictions by choosing one small safe fix.

## Claude peer review
$(sed -n '1,220p' "$peer_dir/claude.txt" 2>/dev/null || true)

## Kimi peer review
$(sed -n '1,220p' "$peer_dir/kimi.txt" 2>/dev/null || true)
PROMPT
  fi
}

build_peer_context() {
  local iteration=$1
  local context_file=$2

  {
    echo "# Muchanipo Autofix Peer Context"
    echo
    echo "- Iteration: $iteration"
    echo "- Branch: $(git branch --show-current)"
    echo "- HEAD: $(git log -1 --oneline)"
    echo
    echo "## Git Status"
    git status --short || true
    echo
    echo "## Recent Commits"
    git log --oneline -10 || true
    echo
    echo "## Current Autofix Summary"
    sed -n '1,180p' "$SUMMARY" 2>/dev/null || true
    echo
    echo "## Backlog"
    sed -n '1,260p' autoresearch.md 2>/dev/null || true
  } >"$context_file"
}

write_peer_prompt() {
  local reviewer=$1
  local context_file=$2
  local prompt_file=$3

  cat >"$prompt_file" <<PROMPT
You are the $reviewer peer in an unattended Muchanipo app hardening loop.

Task:
- Read the context below.
- Do not edit files.
- Identify the single highest-value next small fix, or return NO_CHANGE if no safe, reviewable fix remains.
- Prefer concrete defects with exact files/tests over broad product ideas.
- Classify findings as CRITICAL or MINOR.
- Keep the answer concise enough for another agent to act on.

Context:
$(cat "$context_file")
PROMPT
}

run_peer_reviewer() {
  local reviewer=$1
  local bin=$2
  local prompt_file=$3
  local out_file=$4
  local timeout_seconds=$PEER_TIMEOUT_SECONDS

  if [[ "$reviewer" == "claude" ]]; then
    timeout_seconds=$CLAUDE_TIMEOUT_SECONDS
  elif [[ "$reviewer" == "kimi" ]]; then
    timeout_seconds=$KIMI_TIMEOUT_SECONDS
  fi

  python3 - "$reviewer" "$bin" "$ROOT" "$prompt_file" "$out_file" "$timeout_seconds" "$CLAUDE_MAX_BUDGET_USD" <<'PY'
import pathlib
import subprocess
import sys

reviewer, binary, root, prompt_path, out_path, timeout_s, claude_budget = sys.argv[1:8]
prompt = pathlib.Path(prompt_path).read_text(encoding="utf-8")
out = pathlib.Path(out_path)
timeout = int(timeout_s)

if reviewer == "claude":
    cmd = [
        binary,
        "-p",
        "--output-format",
        "text",
        "--permission-mode",
        "plan",
        "--tools",
        "",
        "--no-session-persistence",
        "--max-budget-usd",
        claude_budget,
        prompt,
    ]
    kwargs = {}
elif reviewer == "kimi":
    cmd = [binary, "--work-dir", root, "--print", "--final-message-only", "--input-format", "text"]
    kwargs = {"input": prompt}
else:
    raise SystemExit(f"unsupported reviewer: {reviewer}")

try:
    completed = subprocess.run(
        cmd,
        cwd=root,
        text=True,
        capture_output=True,
        timeout=timeout,
        **kwargs,
    )
except FileNotFoundError as exc:
    out.write_text(f"NO_CHANGE\n\nReviewer unavailable: {exc}\n", encoding="utf-8")
    raise SystemExit(0)
except subprocess.TimeoutExpired as exc:
    stdout = exc.stdout or ""
    stderr = exc.stderr or ""
    out.write_text(
        f"NO_CHANGE\n\nReviewer timed out after {timeout}s.\n\nSTDOUT:\n{stdout}\n\nSTDERR:\n{stderr}\n",
        encoding="utf-8",
    )
    raise SystemExit(0)

text = (completed.stdout or "").strip()
err = (completed.stderr or "").strip()
if completed.returncode != 0:
    out.write_text(
        f"NO_CHANGE\n\nReviewer exited {completed.returncode}; treating as advisory failure.\n\nSTDOUT:\n{text}\n\nSTDERR:\n{err}\n",
        encoding="utf-8",
    )
else:
    out.write_text((text or "NO_CHANGE") + "\n", encoding="utf-8")
PY
}

run_peer_reviews() {
  local iteration=$1
  local peer_dir="$LOG_DIR/${RUN_ID}-iteration-${iteration}-peers"
  local context_file="$peer_dir/context.md"

  mkdir -p "$peer_dir"
  build_peer_context "$iteration" "$context_file"
  write_peer_prompt "Claude" "$context_file" "$peer_dir/claude.prompt.md"
  write_peer_prompt "Kimi" "$context_file" "$peer_dir/kimi.prompt.md"

  echo "[autofix] iteration $iteration peer review: claude" >&2
  run_peer_reviewer "claude" "$CLAUDE_BIN" "$peer_dir/claude.prompt.md" "$peer_dir/claude.txt" || true
  echo "[autofix] iteration $iteration peer review: kimi" >&2
  run_peer_reviewer "kimi" "$KIMI_BIN" "$peer_dir/kimi.prompt.md" "$peer_dir/kimi.txt" || true

  echo "$peer_dir"
}

echo "[autofix] writing results to $RESULTS"
echo "[autofix] max iterations: $MAX_ITERATIONS, sleep: ${SLEEP_SECONDS}s"

no_change_count=0
for ((i = 1; i <= MAX_ITERATIONS; i++)); do
  log="$LOG_DIR/${RUN_ID}-iteration-${i}.log"
  last_message="$LOG_DIR/${RUN_ID}-iteration-${i}.final.txt"
  peer_dir=""
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
  if [[ "$PEER_REVIEW" == "1" ]]; then
    peer_dir=$(run_peer_reviews "$i")
  fi

  status="failed"
  if worker_prompt "$peer_dir" | "$CODEX_BIN" exec --full-auto -C "$ROOT" -o "$last_message" - >"$log" 2>&1; then
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
      patch="$LOG_DIR/${RUN_ID}-iteration-${i}.failed.patch"
      git diff --binary >"$patch" || true
      git status --short >"$LOG_DIR/${RUN_ID}-iteration-${i}.failed-status.txt" || true
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

  json_append "{\"run_id\": \"$RUN_ID\", \"iteration\": $i, \"status\": \"$status\", \"head_before\": \"$head_before\", \"head_after\": \"$head_after\", \"log\": \"$log\", \"final_message\": \"$last_message\", \"peer_dir\": \"$peer_dir\"}"
  write_summary
  echo "[autofix] iteration $i status=$status head=$head_after"

  if [[ "$status" == "blocked" ]]; then
    exit 1
  fi

  if [[ "$status" == "no_change" ]]; then
    no_change_count=$((no_change_count + 1))
  else
    no_change_count=0
  fi

  if [[ "$no_change_count" -ge "$NO_CHANGE_LIMIT" ]]; then
    echo "[autofix] stopping after $no_change_count consecutive no-change iterations"
    break
  fi

  if [[ "$i" -lt "$MAX_ITERATIONS" ]]; then
    sleep "$SLEEP_SECONDS"
  fi
done
