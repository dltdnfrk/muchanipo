# MuchaNipo — Autonomous Second Brain Engine

> Karpathy Autoresearch + MiroFish Crowd Intelligence + GBrain Pattern + Human-in-the-Loop

AI가 문서를 인제스트하고, 다중 페르소나 Council이 원본을 직접 검색하며 토론하고, 사람이 검증한 지식만 축적하는 자율 리서치 엔진.

## Architecture

```
raw/ (Human-owned)          wiki/ (LLM-owned)
  └── PDF, MD, TXT ──────┐    └── Compiled pages
                          │         index.md (catalog)
                          ▼         log.md (audit)
              ┌─────────────────┐
              │  muchanipo-ingest │  ← Karpathy Wiki pattern
              │  + ontology       │
              └────────┬────────┘
                       ▼
              ┌─────────────────┐
              │  insight-forge   │  ← MiroFish InsightForge
              │  (5W1H → RRF)   │
              └────────┬────────┘
                       ▼
              ┌─────────────────┐
              │  Council         │  ← MiroFish Crowd Sim
              │  (N personas)    │     + local vault-search adapter
              └────────┬────────┘
                       ▼
              ┌─────────────────┐
              │  eval-agent      │  ← HITL Quality Gate
              │  10-axis scoring │     + measured citation/density axes
              └────────┬────────┘
                 ┌─────┼─────┐
                 ▼     ▼     ▼
              PASS  UNCERTAIN FAIL
               │      │       │
               │      ▼       └→ discard
               │  signoff-queue
               │  (Plannotator UI)
               │      │
               │   ✅/❌/✏️
               ▼      ▼
              ┌─────────────────┐
              │  Obsidian Vault  │  ← GBrain pattern
              │  Compiled Truth  │     (overwrite)
              │  + Timeline      │     (append-only)
              └─────────────────┘
                       ▼
              ┌─────────────────┐
              │  rubric-learner  │  ← Self-improving
              │  (20+ feedbacks) │     quality gate
              └─────────────────┘
```

## Inspirations & Attribution

| Concept | Original | What we adopted |
|---------|----------|-----------------|
| **Autoresearch** | [karpathy/autoresearch](https://github.com/karpathy/autoresearch) | `program.md` config, autonomous loop, NEVER STOP |
| **LLM Wiki** | [Karpathy gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) | `raw/` vs `wiki/` ownership, `index.md`, `log.md` |
| **MiroFish** | [666ghj/MiroFish](https://github.com/666ghj/MiroFish) | InsightForge (query decomposition + RRF), ReACT reports |
| **GBrain** | [garrytan/gbrain](https://github.com/garrytan/gbrain) | Compiled Truth + Timeline pattern |

## Project Structure

```
muchanipo/
├── src/
│   ├── muchanipo/
│   │   ├── server.py             # CLI entrypoint
│   │   └── terminal.py           # terminal home, dashboard, run artifacts
│   ├── pipeline/
│   │   ├── runner.py             # CLI/TUI product core facade
│   │   ├── idea_to_council.py    # 6-stage research/council/report pipeline
│   │   └── reference_inventory.py # reference runtime readiness
│   ├── research/
│   │   └── academic/             # OpenAlex/Crossref/Semantic Scholar/etc.
│   ├── search/
│   │   ├── insight-forge.py       # 5W1H query decomposition + RRF fusion
│   │   └── react-report.py        # Think→Act→Observe→Write reports
│   ├── council/                   # persona generation, diversity, sessions
│   ├── evidence/                  # provenance and citation grounding
│   ├── report/                    # chapter mapping + pyramid formatting
│   ├── hitl/
│   │   ├── plannotator_adapter.py # markdown/auto-approve HITL gate
│   │   └── plannotator_http.py    # optional external HITL adapter
│   └── execution/providers/       # Claude/Gemini/Kimi/Codex/OpenAI/Ollama
├── bin/muchanipo                  # local executable shim
├── app/muchanipo-tauri/           # viewer/control shell over CLI events
├── docs/                          # JSON contracts, live wiring, references
├── raw/                           # Human-owned source drop zone
├── wiki/                          # LLM-owned compiled knowledge
│   ├── index.md                   # Page catalog
│   └── log.md                     # Append-only audit log
├── vault/                         # local persona/insight seeds
└── reports/                       # generated reports
```

## Dream Cycle (nightly vault digest)

`tools/dream_cycle.sh` runs the dream-cycle digest over `vault/personas/` and
`vault/insights/`, deduplicates repeated observations, and writes a cluster
summary markdown into `logs/dream-cycle/` (or wherever `--output-dir` points).

```bash
# manual trigger (writes summary to logs/dream-cycle/dream-summary-<ts>.md)
tools/dream_cycle.sh

# preview without writing
tools/dream_cycle.sh --no-write

# alternate vault root or threshold
tools/dream_cycle.sh --vault /path/to/vault --threshold 5
```

Recommended cron schedule (KST 03:00 daily — operator-installed; the script
intentionally does **not** modify your crontab):

```cron
0 3 * * *  cd /path/to/muchanipo && tools/dream_cycle.sh >> logs/dream-cycle.log 2>&1
```

Stdlib-only — no external LLM calls.

## Quick Start

### Terminal-first research app

Muchanipo's product core is the Python CLI/TUI runner. The Tauri app is a
viewer/control shell over the same event stream.

```bash
# Prove the product works without provider credentials
muchanipo demo

# Open the terminal app home, like codex/claude/kimi/opencode
muchanipo

# Direct topic shortcut
muchanipo "딸기 농가용 저비용 분자진단 키트 시장성"

# Explicit modes
muchanipo run "딸기 진단키트 시장성" --offline
muchanipo tui "딸기 진단키트 시장성" --online
muchanipo run "딸기 진단키트 시장성" --depth shallow --offline
muchanipo doctor
muchanipo status
muchanipo runs
muchanipo contracts
muchanipo references
muchanipo orchestrate

# Scriptable inspection
muchanipo doctor --json
muchanipo status --json
muchanipo runs --json --limit 5
muchanipo contracts --json
muchanipo references --json
muchanipo orchestrate --json
muchanipo orchestrate --cleanup-workers --dry-run --json
```

The no-argument home screen reads the same run summaries and shows the latest
runs plus the most recent failed run before the command menu.

JSON inspection commands return stable objects with `schema_version`,
`command`, and command-specific payloads:

- `doctor --json`: `status`, `checks`, `cli_statuses`, `recommendations`
- `status --json`: `providers`
- `runs --json`: `runs_dir`, `limit`, `runs`
- `references --json`: `stages`, `references`, `gaps`, `not_ready_references`, `license_warnings`
- `orchestrate --json`: `session`, `plan`, `windows`, `panes`, `operators`, `warnings`

See `docs/cli-json-contracts.md` or `muchanipo contracts --json` for the
current required top-level keys.

`muchanipo demo` is the fastest product smoke path. It runs a deterministic
offline topic, skips the interview, and writes the same `REPORT.md`,
`events.jsonl`, and `summary.json` artifacts as normal runs.

Before a pre-release audit, run:

```bash
bash scripts/release_check.sh
```

The release check runs focused orchestration tests, CLI/TUI tests, the full
Python suite, diff hygiene, orchestration status/dry-run cleanup, JSON
contracts, the offline demo, generated-artifact hygiene, a Python 3.11 wheel
build, an installed console-script smoke, and an installed `python -m
muchanipo` smoke when `python3.11` is available.

Passing this script proves deterministic offline packaging and CLI contracts. It
does not prove live provider/HITL behavior or full upstream reference parity.
Use `muchanipo references --json` to check `not_ready_references`, and run a
separate opt-in live smoke before making live-research or 99% implementation
claims.

Autoresearch depth is explicit: `--depth shallow` targets a quick interactive
pass, `--depth deep` keeps the default full ten-layer council budget, and
`--depth max` records extended test-time-compute intent for comprehensive
background runs. The six-stage Muchanipo flow remains intact at every depth.

`muchanipo references` reports which reference-project ideas are backed by
local runtime code, which are still gaps, and which carry license warnings. It
does not imply that full upstream repositories are vendored.

`muchanipo orchestrate` reports the tmux/smux operator contract used for
multi-agent work: window 0 is the protected operator hub, worker windows are
1-4, OpenCode is expected to use Hephaestus Deep Agent GPT-5.5, and cleanup
commands only target verified worker windows. Verification requires both the
expected worker window name and a pane title marker such as
`muchanipo-worker:codex`. Use `--cleanup-workers --dry-run` before destructive
cleanup; actual cleanup additionally requires `--force`. Pane captures
requested with `--include-capture` are redacted before output.

Run artifacts are written under `~/.local/share/muchanipo/runs/<run-id>/` by
default:

- `REPORT.md` — final report
- `events.jsonl` — append-only execution event log
- `summary.json` — run metadata and paths

Muchanipo does not read Claude/Gemini/Kimi/Codex token files. It invokes the
installed CLIs and lets each CLI own its own login/session.

### Legacy document tools

```bash
# 1. Drop a document
cp your-document.pdf raw/

# 2. Ingest with ontology extraction
python3 src/ingest/muchanipo-ingest.py raw/your-document.pdf \
  --wing research --room topic \
  --strategy semantic --extract-ontology

# 3. Or scan all raw/ files at once
python3 src/ingest/muchanipo-ingest.py --scan-raw --wing research

# 4. Search with InsightForge
python3 src/search/insight-forge.py "your research question" --depth deep

# 5. After Council runs, evaluate results (v2.1 — 11-axis 100/110 scale)
python3 src/eval/eval-agent.py council-report.json

# 5b. Optional: citation grounding pass before vault write
python3 src/eval/citation_grounder.py council-report.json --verbose

# 6. Review UNCERTAIN items (HITL queue + HTML report)
python3 src/hitl/signoff-queue.py list
python3 src/hitl/signoff-report.py sq-xxx --queue-dir signoff-queue --reports-dir reports --open
python3 src/hitl/signoff-queue.py approve sq-xxx

# 7. After 20+ feedbacks, evolve the rubric (11-axis aware)
python3 src/eval/rubric-learner.py analyze
python3 src/eval/rubric-learner.py evolve
```

## Requirements

- Python 3.11+ for packaged installs.
- `httpx>=0.28` for academic API and optional HTTP HITL adapters.
- Optional provider CLIs for online runs: Claude Code, Gemini, Kimi, Codex, or OpenCode.
- Optional API keys for provider/API-backed online runs.
- Optional [Obsidian](https://obsidian.md/) vault frontend.

Offline mode and `muchanipo demo` remain deterministic and credential-free.

## HITL Quality Gate

```
Score 70+/100  → PASS       → Direct to vault                    (v2.0 baseline)
Score 50-69    → UNCERTAIN  → Sign-off queue (human review)
Score <50      → FAIL       → Discard + log

v2.1 (citation_fidelity 11번째 축 활성화 시): pass 77/110, uncertain 55/110

After 20+ human decisions → rubric-learner auto-adjusts thresholds
```

## License

MIT
