#!/usr/bin/env bash
# Append-only overnight quality loop inspired by pi-autoresearch.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

MAX_ITERATIONS=${MAX_ITERATIONS:-96}
SLEEP_SECONDS=${SLEEP_SECONDS:-300}
RESULTS=${RESULTS:-"$ROOT/.omc/autoresearch/results.jsonl"}
SUMMARY=${SUMMARY:-"$ROOT/.omc/autoresearch/summary.md"}

mkdir -p "$(dirname "$RESULTS")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "[overnight] python3 is required" >&2
  exit 127
fi

append_result() {
  local status="$1"
  local output_file="$2"
  local started_at="$3"
  local ended_at="$4"

  python3 - "$RESULTS" "$status" "$output_file" "$started_at" "$ended_at" <<'PY'
import json
import pathlib
import sys

results_path = pathlib.Path(sys.argv[1])
status = sys.argv[2]
output_path = pathlib.Path(sys.argv[3])
started_at = sys.argv[4]
ended_at = sys.argv[5]

metrics = {}
raw = output_path.read_text(encoding="utf-8", errors="replace")
for line in raw.splitlines():
    if not line.startswith("METRIC "):
        continue
    key_value = line[len("METRIC "):].split("=", 1)
    if len(key_value) != 2:
        continue
    key, value = key_value
    try:
        metrics[key] = float(value)
    except ValueError:
        metrics[key] = value

entry = {
    "type": "run",
    "status": status,
    "started_at": started_at,
    "ended_at": ended_at,
    "metrics": metrics,
    "output_path": str(output_path),
}
with results_path.open("a", encoding="utf-8") as f:
    f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
PY
}

write_summary() {
  python3 - "$RESULTS" "$SUMMARY" <<'PY'
import json
import pathlib
import sys

results_path = pathlib.Path(sys.argv[1])
summary_path = pathlib.Path(sys.argv[2])

runs = []
if results_path.exists():
    for line in results_path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") == "run":
            runs.append(entry)

best = max(
    runs,
    key=lambda entry: entry.get("metrics", {}).get("quality_score", float("-inf")),
    default=None,
)
latest = runs[-1] if runs else None

lines = [
    "# Muchanipo Overnight Loop",
    "",
    f"- Runs: {len(runs)}",
    f"- Latest status: {latest.get('status') if latest else 'none'}",
    f"- Latest quality_score: {latest.get('metrics', {}).get('quality_score') if latest else 'n/a'}",
    f"- Best quality_score: {best.get('metrics', {}).get('quality_score') if best else 'n/a'}",
    "",
    "## Recent Runs",
]
for entry in runs[-10:]:
    metrics = entry.get("metrics", {})
    lines.append(
        f"- {entry.get('ended_at')} {entry.get('status')} "
        f"quality={metrics.get('quality_score')} failures={metrics.get('failures')} "
        f"duration={metrics.get('duration_seconds')}"
    )

summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
}

echo "[overnight] writing results to $RESULTS"
echo "[overnight] max iterations: $MAX_ITERATIONS, sleep: ${SLEEP_SECONDS}s"

for ((i = 1; i <= MAX_ITERATIONS; i++)); do
  started_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  output_file="$ROOT/.omc/autoresearch/logs/run-${i}.out"
  mkdir -p "$(dirname "$output_file")"

  echo "[overnight] iteration $i started at $started_at"
  status="passed"
  if ! ./autoresearch.sh >"$output_file" 2>&1; then
    status="failed"
    tail -80 "$output_file" || true
  fi

  ended_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  append_result "$status" "$output_file" "$started_at" "$ended_at"
  write_summary
  echo "[overnight] iteration $i $status; summary: $SUMMARY"

  if [[ "$i" -lt "$MAX_ITERATIONS" ]]; then
    sleep "$SLEEP_SECONDS"
  fi
done
