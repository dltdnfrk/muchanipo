#!/usr/bin/env bash
# omc-auto-team.sh — split 자동 + worker done.txt 폴링 후 자동 shutdown
# 사용:
#   bash tools/omc-auto-team.sh <N> <agent> <task> <lock-dir> [timeout_min=60] [poll_sec=30]
# 예:
#   bash tools/omc-auto-team.sh 4 codex \
#     "muchanipo C2 sprint... ASSIGNMENT_X.md 정독 후 진행" \
#     /Users/hyunjun/Documents/neobio/_research/.codex-locks-c2 60 30
set -euo pipefail

N="${1:?N 워커 수 필요}"
AGENT="${2:?agent type (codex/claude/gemini)}"
TASK="${3:?task description}"
LOCK_DIR="${4:?lock dir 절대경로}"
TIMEOUT_MIN="${5:-60}"
POLL_SEC="${6:-30}"

mkdir -p "$LOCK_DIR"
TIMEOUT_SEC=$((TIMEOUT_MIN * 60))
START=$(date +%s)

# ----------------------------------------------------------------------------
# 1) Spawn (no --new-window → 현재 윈도우에 자동 split)
# ----------------------------------------------------------------------------
echo "[$(date '+%H:%M:%S')] omc team $N:$AGENT spawn (split 자동)..."
TEAM_OUT=$(omc team "$N:$AGENT" "$TASK" 2>&1) || {
  echo "$TEAM_OUT" >&2
  echo "❌ spawn 실패" >&2
  exit 2
}
echo "$TEAM_OUT" | tail -10

TEAM_NAME=$(echo "$TEAM_OUT" | grep -oE 'Team started: [a-zA-Z0-9-]+' | head -1 | sed 's/Team started: //')
if [ -z "$TEAM_NAME" ]; then
  echo "❌ team name 추출 실패 — 자동 shutdown 불가" >&2
  exit 3
fi
echo "▶ Team: $TEAM_NAME"
echo "▶ Lock: $LOCK_DIR"
echo "▶ Timeout: ${TIMEOUT_MIN}m, poll every ${POLL_SEC}s"
echo ""

# ----------------------------------------------------------------------------
# 2) Polling — done.txt 카운트가 N에 도달할 때까지
# ----------------------------------------------------------------------------
LAST_DONE=-1
while true; do
  ELAPSED=$(( $(date +%s) - START ))
  ELAPSED_MIN=$(( ELAPSED / 60 ))
  DONE_COUNT=$(find "$LOCK_DIR" -mindepth 2 -maxdepth 2 -name done.txt 2>/dev/null | wc -l | tr -d ' ')

  # done count 변화 시에만 출력 (스팸 방지)
  if [ "$DONE_COUNT" -ne "$LAST_DONE" ]; then
    echo "[$(date '+%H:%M:%S')] $DONE_COUNT/$N done (${ELAPSED_MIN}m elapsed)"
    LAST_DONE=$DONE_COUNT
  fi

  if [ "$DONE_COUNT" -ge "$N" ]; then
    echo "✅ 모든 워커 done"
    break
  fi

  if [ "$ELAPSED" -ge "$TIMEOUT_SEC" ]; then
    echo "⏰ timeout (${TIMEOUT_MIN}m 초과) — 강제 shutdown"
    break
  fi

  sleep "$POLL_SEC"
done

# ----------------------------------------------------------------------------
# 3) Auto shutdown
# ----------------------------------------------------------------------------
echo ""
echo "[$(date '+%H:%M:%S')] omc team shutdown $TEAM_NAME --force"
omc team shutdown "$TEAM_NAME" --force 2>&1 | tail -3 || {
  echo "⚠ shutdown 실패 (이미 종료됐을 수 있음)" >&2
}

echo ""
echo "=== 완료 요약 ==="
TOTAL_ELAPSED=$(( $(date +%s) - START ))
echo "▶ Team: $TEAM_NAME"
echo "▶ Done: $DONE_COUNT/$N"
echo "▶ Elapsed: $((TOTAL_ELAPSED / 60))m $((TOTAL_ELAPSED % 60))s"
echo "▶ Lock dir: $LOCK_DIR"
ls -la "$LOCK_DIR" 2>/dev/null | head -20
