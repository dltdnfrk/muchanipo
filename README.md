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
              │  (N personas)    │     + MemPalace search
              └────────┬────────┘
                       ▼
              ┌─────────────────┐
              │  eval-agent      │  ← HITL Quality Gate
              │  4-axis scoring  │
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
│   ├── pipeline/
│   │   └── muchanipo-ingest.py    # Document ingest + ontology extraction
│   ├── search/
│   │   ├── insight-forge.py       # 5W1H query decomposition + RRF fusion
│   │   └── react-report.py        # Think→Act→Observe→Write reports
│   ├── hitl/
│   │   ├── eval-agent.py          # 4-axis auto-scoring (40pt scale)
│   │   ├── signoff-queue.py       # approve/reject/modify CLI
│   │   ├── signoff-report.py      # HTML report generator
│   │   └── rubric-learner.py      # Feedback-driven rubric evolution
│   └── council/                   # (planned) Council orchestrator
├── config/
│   ├── program.md                 # Research axes & exploration rules
│   ├── rubric.json                # Eval scoring config (v1.0.0)
│   └── config.json                # Pipeline config
├── skills/
│   ├── muchanipo.md               # Orchestrator skill (Claude Code)
│   └── arc-council.md             # Council debate engine skill
├── agents/
│   └── arc-wiki.md                # Wiki storage agent
├── raw/                           # Human-owned source drop zone
├── wiki/                          # LLM-owned compiled knowledge
│   ├── index.md                   # Page catalog
│   └── log.md                     # Append-only audit log
├── signoff-queue/                 # Pending human review items
├── rubric-history/                # Rubric version backups
├── reports/                       # Generated HTML reports
└── logs/                          # Ingest & ontology logs
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
# Open the terminal app home, like codex/claude/kimi/opencode
muchanipo

# Direct topic shortcut
muchanipo "딸기 농가용 저비용 분자진단 키트 시장성"

# Explicit modes
muchanipo run "딸기 진단키트 시장성" --offline
muchanipo tui "딸기 진단키트 시장성" --online
muchanipo doctor
muchanipo status
muchanipo runs

# Scriptable inspection
muchanipo doctor --json
muchanipo status --json
muchanipo runs --json --limit 5
```

The no-argument home screen reads the same run summaries and shows the latest
runs plus the most recent failed run before the command menu.

JSON inspection commands return stable objects with `schema_version`,
`command`, and command-specific payloads:

- `doctor --json`: `status`, `checks`, `cli_statuses`, `recommendations`
- `status --json`: `providers`
- `runs --json`: `runs_dir`, `limit`, `runs`

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

- Python 3.8+
- No external dependencies (stdlib only)
- [MemPalace](https://github.com/mempalace) for knowledge graph storage
- [Claude Code](https://claude.com/claude-code) for Council orchestration
- [Obsidian](https://obsidian.md/) for vault frontend (optional)

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
