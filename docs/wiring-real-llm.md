# Wiring Muchanipo to real LLMs

> Phase 3 — replace offline mocks with live LLM calls so the Tauri app
> produces a research report based on actual reasoning, not fixture text.

## TL;DR

```bash
bash scripts/setup_keys.sh         # writes .env scaffold
$EDITOR .env                        # add at least ANTHROPIC_API_KEY
source .env
ANTHROPIC_OFFLINE=                  # unset to enable real calls
python3 -m muchanipo serve --topic "딸기 진단키트 시장성" --pipeline full \
  --report-path /tmp/REPORT.md
```

If at least one provider key is set, the corresponding stage will dispatch
to the real API. Other stages remain on the offline fallback so a partial
key set still produces an end-to-end report.

## Stage → Provider routing (PRD §8.1)

| Stage      | Primary       | Fallback chain                            | Env switch                        |
|------------|---------------|-------------------------------------------|------------------------------------|
| intake     | Gemini Flash  | gemini → anthropic → mock                | `GEMINI_API_KEY`                  |
| interview  | Claude Sonnet | anthropic → gemini → mock                | `ANTHROPIC_API_KEY`               |
| targeting  | Gemini        | gemini → anthropic → mock                | `GEMINI_API_KEY`                  |
| research   | Gemini Pro    | gemini → kimi → anthropic → mock         | `GEMINI_API_KEY` / `KIMI_API_KEY` |
| evidence   | Kimi K2.6     | kimi → gemini → anthropic → mock         | `KIMI_API_KEY`                    |
| council    | Claude Opus   | anthropic → gemini → mock                | `ANTHROPIC_API_KEY`               |
| report     | Claude Sonnet | anthropic → gemini → mock                | `ANTHROPIC_API_KEY`               |
| eval       | Codex / GPT-5 | codex → anthropic → mock                 | `OPENAI_API_KEY` or `CODEX_BIN`   |

Qwen 3.6 로컬 provider는 보류 (PRD §15.3 Phase 3+).

## Offline mocks

Each provider returns deterministic mock text when its key is missing OR
the corresponding `*_OFFLINE=1` env var is set. This keeps `pytest`,
`bash scripts/e2e_smoke.sh`, and the Tauri app working in CI/local-dev
without any keys. Real-mode behavior is opt-in.

| Provider  | Offline trigger                                |
|-----------|------------------------------------------------|
| anthropic | `ANTHROPIC_API_KEY` unset or `ANTHROPIC_OFFLINE=1` |
| gemini    | `GEMINI_API_KEY` unset or `GEMINI_OFFLINE=1`   |
| kimi      | `KIMI_API_KEY` unset or `KIMI_OFFLINE=1`       |
| codex     | `OPENAI_API_KEY` and `CODEX_BIN` both missing or `CODEX_OFFLINE=1` |
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

# real LLM (auto-skipped without keys)
ANTHROPIC_API_KEY=sk-... pytest tests/test_real_llm_smoke.py -v
```

## Tauri app

The bundled app (`Muchanipo.app`) reads `.env` from the working directory.
For an installed `.app`, set keys in your shell login script
(`~/.zshrc` exports) or run from the project directory.

## Limitations / open work

- No streaming token UI yet — councils stream is collapsed to round-level
  events. PRD §6 streaming token feed is a Phase 3+ polish item.
- Plannotator HITL still defaults to `mode='markdown'` until a user sets
  `PLANNOTATOR_API_KEY`. Markdown mode requires manual file edit to clear
  each gate.
- Citation grounder is character + n-gram only — semantic embedding
  comparison would be a separate Phase 3 ticket.
