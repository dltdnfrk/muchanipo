#!/usr/bin/env bash
set -euo pipefail

# 사용자가 명시적으로 실행하는 Nemotron-Personas-Korea 다운로드 wrapper.
# 대용량/라이선스 확인이 필요한 데이터이므로 자동 실행하지 않는다.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST_DIR="${1:-$ROOT_DIR/vault/personas/seeds/korea}"
DATASET="nvidia/Nemotron-Personas-Korea"

mkdir -p "$DEST_DIR"

if command -v huggingface-cli >/dev/null 2>&1; then
  huggingface-cli download "$DATASET" --repo-type dataset --local-dir "$DEST_DIR"
elif command -v hf >/dev/null 2>&1; then
  hf download "$DATASET" --repo-type dataset --local-dir "$DEST_DIR"
else
  cat >&2 <<EOF
huggingface-cli 또는 hf 명령을 찾을 수 없습니다.

설치 후 다시 실행하세요:
  pip install -U huggingface_hub

Dataset:
  https://huggingface.co/datasets/$DATASET

Destination:
  $DEST_DIR
EOF
  exit 127
fi

cat <<EOF
Nemotron-Personas-Korea 다운로드가 완료되었습니다.
필요하면 parquet 파일을 JSONL/CSV로 export한 뒤 KoreaPersonaSampler에 전달하세요.

Destination:
  $DEST_DIR
EOF
