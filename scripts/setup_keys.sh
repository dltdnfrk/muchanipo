#!/usr/bin/env bash
# Interactive helper to populate Muchanipo .env with provider API keys.
# Run from the repo root: bash scripts/setup_keys.sh
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
ENV_FILE="$ROOT/.env"

if [[ -f "$ENV_FILE" ]]; then
  cp "$ENV_FILE" "$ENV_FILE.bak.$(date +%s)"
  echo "[setup_keys] backed up existing .env"
fi

cat > "$ENV_FILE" <<'EOF'
# Muchanipo provider keys (PRD-v2 §8.1).
# Leave any line empty to keep that provider in offline mock mode.

# Anthropic Claude (Council, Interview, Report)
ANTHROPIC_API_KEY=

# Moonshot Kimi K2.6 (Evidence)
KIMI_API_KEY=

# Google Gemini (Intake, Targeting, Research)
GEMINI_API_KEY=
GOOGLE_API_KEY=

# OpenAI / Codex CLI (Eval)
OPENAI_API_KEY=
CODEX_BIN=

# OpenAlex polite pool (free, just needs an email)
OPENALEX_EMAIL=

# Plannotator HITL (Phase 3 — optional, markdown fallback works without)
PLANNOTATOR_API_KEY=
PLANNOTATOR_ENDPOINT=

# Per-research budget cap (USD). Default $0.5 per PRD §8.3.
MUCHANIPO_BUDGET_USD=0.5
EOF

echo "[setup_keys] wrote $ENV_FILE"
echo "[setup_keys] Edit it (e.g. nano $ENV_FILE) and add your keys."
echo "[setup_keys] Then: source .env && python3 -m muchanipo serve --topic '...' --pipeline full"
