#!/usr/bin/env bash
# E2E smoke — Python pipeline 단독 실행 → 6 chapter MBB 보고서까지 검증.
# Tauri shell 없이 backend만 확인. PR 머지 전 sanity check.

set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
TMP="${TMPDIR:-/tmp}"
REPORT="$TMP/muchanipo_smoke_report.md"
EVENTS="$TMP/muchanipo_smoke_events.jsonl"

rm -f "$REPORT" "$EVENTS"

cd "$ROOT"

echo "[smoke] running full pipeline…"
python3 -m muchanipo serve \
  --topic "딸기 진단키트 시장성 (smoke)" \
  --pipeline full \
  --no-wait \
  --report-path "$REPORT" \
  > "$EVENTS"

# 1) report file exists
if [[ ! -f "$REPORT" ]]; then
  echo "[smoke] FAIL: report not generated at $REPORT"
  exit 1
fi

# 2) all six chapters present
for n in 1 2 3 4 5 6; do
  if ! grep -q "^## Chapter $n" "$REPORT"; then
    echo "[smoke] FAIL: Chapter $n missing"
    exit 1
  fi
done

# 3) all 8 stage events emitted
for s in intake interview targeting research evidence council report finalize; do
  if ! grep -q "\"stage\": \"$s\"" "$EVENTS"; then
    echo "[smoke] FAIL: stage $s missing in events"
    exit 1
  fi
done

# 4) final_report event with markdown
if ! grep -q "\"event\": \"final_report\"" "$EVENTS"; then
  echo "[smoke] FAIL: final_report event missing"
  exit 1
fi

# 5) done event terminates the stream
if ! tail -1 "$EVENTS" | grep -q "\"event\": \"done\""; then
  echo "[smoke] FAIL: stream did not end with done event"
  exit 1
fi

echo "[smoke] PASS: 6 chapters + 8 stages + final_report + done"
echo "[smoke] Report : $REPORT"
echo "[smoke] Events : $EVENTS"
