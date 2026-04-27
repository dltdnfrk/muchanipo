#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
REPORT="${TMPDIR:-/tmp}/muchanipo_smoke_report.md"
EVENTS="${TMPDIR:-/tmp}/muchanipo_smoke_events.jsonl"
rm -f "$REPORT" "$EVENTS"

cd "$ROOT"
python3 -m muchanipo serve \
  --topic "딸기 진단키트 시장성 (smoke)" \
  --pipeline full \
  --no-wait \
  --report-path "$REPORT" \
  > "$EVENTS"

test -f "$REPORT" || { echo "FAIL: report not generated"; exit 1; }
for n in 1 2 3 4 5 6; do
  grep -q "## Chapter $n" "$REPORT" || { echo "FAIL: Chapter $n missing"; exit 1; }
done

for s in intake interview targeting research evidence council report finalize; do
  grep -q "\"stage\": \"$s\"" "$EVENTS" \
    || { echo "FAIL: stage $s missing"; exit 1; }
done

echo "PASS: 6 chapters + 8 stages OK"
echo "Report: $REPORT"
