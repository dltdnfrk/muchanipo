# Wiring Muchanipo to real LLMs

> Phase 3 — replace offline mocks with live LLM calls so the Tauri app
> produces a research report based on actual reasoning, not fixture text.

## TL;DR

Personal/local usage should prefer installed CLIs. Muchanipo does not read
Claude Code, Gemini, Kimi, or Codex token files directly; each CLI owns its
own login/session.

```bash
export MUCHANIPO_PREFER_CLI=1
ANTHROPIC_OFFLINE=                  # unset to enable real calls
python3 -m muchanipo serve --topic "딸기 진단키트 시장성" --pipeline full \
  --report-path /tmp/REPORT.md
```

If at least one configured CLI is installed, the corresponding stage will
dispatch to that CLI. API keys remain supported as fallback inputs for
environments that do not have local CLIs.

## Stage → Provider routing (PRD §8.1)

| Stage      | Primary       | Fallback chain                            | Preferred local switch            |
|------------|---------------|-------------------------------------------|------------------------------------|
| intake     | Gemini Flash  | gemini → anthropic → mock                | `MUCHANIPO_PREFER_CLI=1`          |
| interview  | Claude Sonnet | anthropic → gemini → mock                | `MUCHANIPO_PREFER_CLI=1`          |
| targeting  | Gemini        | gemini → anthropic → mock                | `MUCHANIPO_PREFER_CLI=1`          |
| research   | Gemini Pro    | gemini → kimi → anthropic → mock         | `MUCHANIPO_PREFER_CLI=1`          |
| evidence   | Kimi K2.6     | kimi → gemini → anthropic → mock         | `MUCHANIPO_PREFER_CLI=1`          |
| council    | Claude Opus   | anthropic → gemini → mock                | `MUCHANIPO_PREFER_CLI=1`          |
| report     | Claude Sonnet | anthropic → gemini → mock                | `MUCHANIPO_PREFER_CLI=1`          |
| eval       | Codex / GPT-5 | codex → anthropic → mock                 | `CODEX_BIN` or `codex` on PATH    |

Qwen 3.6 로컬 provider는 보류 (PRD §15.3 Phase 3+).

## Offline mocks

Each provider returns deterministic mock text when its local CLI/API access is
missing OR the corresponding `*_OFFLINE=1` env var is set. This keeps `pytest`,
`bash scripts/e2e_smoke.sh`, and CI working without credentials. The installed
Tauri app prefers CLI execution by default; pytest disables implicit CLI
detection unless a test explicitly opts in.

| Provider  | Offline trigger                                |
|-----------|------------------------------------------------|
| anthropic | `claude` CLI/API unavailable or `ANTHROPIC_OFFLINE=1` |
| gemini    | `gemini` CLI/API unavailable or `GEMINI_OFFLINE=1` |
| kimi      | `kimi` CLI/API unavailable or `KIMI_OFFLINE=1` |
| codex     | `codex` CLI/API unavailable or `CODEX_OFFLINE=1` |
| ollama    | not used in Phase 2 (Qwen 3.6 보류)            |

## Cost control

- `MUCHANIPO_BUDGET_USD=0.5` — per-research hard cap. `RunBudget.reserve()`
  returns False when remaining budget is insufficient and the gateway
  falls back through the chain (eventually `mock`) rather than overshooting.
- Append-only audit log lives at `vault/cost-log.jsonl` — every
  call records `stage`, `provider`, `model`, `cost_usd`, `fallback_reason`.
- Run `python3 -m src.governance.cost_simulator <topic>` to estimate cost
  before kicking off a real research session.

## Smoke tests

```bash
# offline (always works)
bash scripts/e2e_smoke.sh

# real LLM through installed CLIs
MUCHANIPO_PREFER_CLI=1 pytest tests/test_real_llm_smoke.py -v
```

## Tauri app

The bundled app (`Muchanipo.app`) prefers installed CLIs. Keep each provider
logged in through its own CLI. API keys in `.env` are optional fallback inputs,
not the default personal-local path.

## Limitations / open work

- No streaming token UI yet — councils stream is collapsed to round-level
  events. PRD §6 streaming token feed is a Phase 3+ polish item.
- Plannotator HITL still defaults to `mode='markdown'` until a user sets
  `PLANNOTATOR_API_KEY`. Markdown mode requires manual file edit to clear
  each gate.
- Citation grounder is character + n-gram only — semantic embedding
  comparison would be a separate Phase 3 ticket.
