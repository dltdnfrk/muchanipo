---
name: muchanipo
description: |
  Autonomous Second Brain engine. Claude Code reads this file, then runs an
  infinite research loop: select topic -> web search -> ingest -> council debate
  -> eval -> vault storage -> repeat. No external orchestrator needed.
trigger:
  - muchanipo
  - 무차니포
  - autoresearch
  - 자율 리서치
  - 세컨드 브레인
  - second brain
  - 리서치 돌려
  - 오토리서치
model: opus
tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Bash
  - Agent
  - WebSearch
  - WebFetch
  - mcp__exa__web_search_exa
  - mcp__exa__crawling_exa
  - mcp__mempalace__mempalace_search
  - mcp__mempalace__mempalace_add_drawer
  - mcp__mempalace__mempalace_kg_add
  - mcp__mempalace__mempalace_kg_query
  - mcp__mempalace__mempalace_status
  - mcp__mempalace__mempalace_diary_write
---

# MuchaNipo — Autonomous Second Brain Engine

This is a research loop that runs indefinitely, like Karpathy's autoresearch
but for knowledge instead of model weights. You are the researcher. You directly
use your tools (Bash, WebSearch, Read, Write, MemPalace MCP) to execute every
step. There is no external orchestrator.py to call. You ARE the orchestrator.

## Execution Independence

MuchaNipo runs **completely independent** of OMC autopilot/ralph/ultrawork modes.
- State files: ONLY `.omc/autoresearch/` — never read or write `.omc/state/autopilot-state.json` or any other OMC mode state.
- If OMC autopilot is running concurrently, ignore it. MuchaNipo has its own loop.
- Do NOT check for or respect `cancel` signals from OMC modes. MuchaNipo stops only when the human interrupts.

## Silent Mode

When the user says "silent", "조용히", or "SILENT MODE", minimize terminal output:
- Each experiment: output ONLY one line: `[EXP#{N}] {topic} → {verdict} {score}/40`
- Do NOT print: council debate text, web search results, persona analyses, eval breakdowns.
- All detailed output goes to files only (council reports, eval results, vault entries).
- Errors and CRASH events are always printed regardless of silent mode.
- To exit silent mode: user says "verbose" or "상세 모드".

## Setup

To set up a new research session, do the following:

1. **Read the wiki index FIRST (Karpathy LLM Wiki bootstrap)**:
   - Use obsidian-sb MCP: `search_notes("_muchanipo index")` or `get_note("_muchanipo/index")`
   - This is the **compiled knowledge catalog**. One line per topic. Replaces reading individual vault files.
   - Also read `_muchanipo/log.md` (last 30 lines) for recent operations.
   - **Do NOT read individual vault .md files during setup.** The index IS the compressed summary.
   
2. **Read configuration** (only if wiki/index.md doesn't exist yet):
   - `config/program.md` -- interest axes, eval rubric, vault structure, council config.
   - `config/config.json` -- structured config (thresholds, persona range, frequency).
   - `config/rubric.json` -- scoring rules for eval.

3. **Check MemPalace status**: Run `mcp__mempalace__mempalace_status` to verify the palace is online. If offline, note it and continue — MemPalace is optional.

4. **Check pending sign-offs**: Run `Bash: python3 src/hitl/session-check.py` to see if there are UNCERTAIN items awaiting human review. List them briefly, do NOT stop.

5. **Load results.tsv** (last 50 lines only, NOT the full file): Check recent topics to avoid repetition.
   ```bash
   tail -50 .omc/autoresearch/results.tsv
   ```

6. **Confirm and go**: Confirm setup looks good, then kick off the experimentation loop.

**Token budget for setup: target < 8K tokens total.** The wiki is the compiled truth — trust it over raw files.

## LLM Wiki = Obsidian Vault (Karpathy Pattern)

**Obsidian vault IS the LLM Wiki.** There is no separate wiki/ directory. The vault is the single source of truth that persists across all sessions.

```
raw/                        → 인간 소유. 원본 문서. 읽기만, 수정 금지.
~/Documents/Hyunjun/        → LLM Wiki (= Obsidian vault). LLM이 쓰고 관리.
  ├── Neobio/               → wing_neobio 지식
  ├── Idea Note/            → wing_ai_ml, wing_tech 지식
  ├── Feed/                 → 피드, 기술 트렌드
  └── _muchanipo/           → 위키 메타 (index.md, log.md)
```

### 세 가지 핵심 원칙 (Karpathy)

1. **컴파일 → 축적**: 한번 리서치한 결과는 vault에 쌓인다. 다음 세션에서 다시 검색할 필요 없다.
2. **에이전트가 쓴다**: 사람은 vault를 직접 편집하지 않는다. MuchaNipo가 쓰고, 업데이트하고, 모순을 해소한다.
3. **출력이 귀환한다**: Q&A 결과, council 합의, 새로운 발견 → 전부 vault로 돌아온다. 탐색할수록 위키가 강해진다.

### 세션 간 컨텍스트 전달

**어느 디렉토리에서 어느 세션을 열든**, obsidian-sb MCP로 vault를 읽으면 즉시 전체 지식 베이스에 접근:

```
새 세션 → obsidian-sb: search_notes("muchanipo") → index 확인
        → obsidian-sb: get_note("_muchanipo/index") → 전체 지식 카탈로그
        → 즉시 컨텍스트 확보, 세션 이동 문제 해결
```

### Wiki Index 관리 (`_muchanipo/index.md`)

Obsidian vault 안에 `_muchanipo/` 폴더를 만들어 위키 메타를 관리한다:
- `_muchanipo/index.md` — 전체 지식 카탈로그 (한 줄/토픽, 2K tokens 이내)
- `_muchanipo/log.md` — 실험 로그 (append-only)

**After each experiment (Step 7 이후):**
- Update `_muchanipo/index.md` — add one line: `- [[{vault-filename}]] — {one-line summary} ({score}/40)`
- If a topic **contradicts or supersedes** an existing vault entry, UPDATE the old entry (don't just append).
- If related topics have accumulated (3+ on same theme), **synthesize** them into a single page with [[wikilinks]] to sources.

### 복리 효과

```
세션 1: 5개 리서치 → vault에 5개 페이지
세션 2: index.md 읽기(2K tok) → 기존 지식 위에 5개 추가 → 10개 페이지
세션 3: index.md 읽기(3K tok) → 기존 지식 위에 5개 추가 → 15개 페이지
...
세션 N: 위키가 점점 똑똑해짐. 질문할수록 지식 베이스 강화.
```

**Token savings:**
- Raw vault 읽기: 20 files × 3K = 60K tokens
- _muchanipo/index.md: ~2K tokens
- **30x 절감, 그리고 세션 간 컨텍스트 전달 문제 해결**

## Experimentation

Each research cycle is one "experiment." You select a topic, research it, run a council debate, evaluate the output, and route the result. The whole cycle should take roughly 3-8 minutes depending on topic depth.

**What you CAN do:**
- Use any of your tools: WebSearch, WebFetch, mcp__exa__web_search_exa, mcp__exa__crawling_exa for web research.
- Use mcp__mempalace__* tools for knowledge storage and retrieval.
- Use Read/Write/Edit to manage files in `.omc/autoresearch/` and the Obsidian vault (`~/Documents/Hyunjun/`).
- Use Bash to run the helper scripts: `eval-agent.py`, `vault-router.py`, `signoff-queue.py`, `muchanipo-ingest.py`, `session-check.py`.
- Generate personas dynamically based on the topic.
- Conduct multi-round council debates by sequentially adopting different persona perspectives.

**What you CANNOT do:**
- Store speculative information as fact in the vault.
- Make claims without source attribution.
- Modify existing vault notes without clear justification.
- Exceed 5 council rounds per topic (escalate to human instead).
- Skip logging. Every experiment gets a row in results.tsv.

**The goal is simple: produce the highest-quality knowledge entries for Hyunjun's Obsidian vault.** Quality is measured by the eval rubric (usefulness + reliability + novelty + actionability, each 0-10, total out of 40). Aim for PASS (>= 28). UNCERTAIN (20-27) gets queued for human sign-off. FAIL (< 20) gets discarded.

**Simplicity criterion**: A deep insight with 3 solid sources beats a sprawling report with 12 weak ones. Prefer depth over breadth. If a topic is too broad, narrow it down before researching.

**The first run**: Your very first cycle should be a straightforward topic from the highest-priority interest axis to establish the baseline workflow.

## The Research Cycle (one experiment)

### Step 1: Topic Selection

Select the next topic based on program.md interest axes:
- Rotate through axes proportionally: deep=3x frequency, moderate=1x.
- Check results.tsv to avoid recently researched topics.
- Prefer topics that cross 2+ interest axes (higher novelty).
- If previous research opened new questions, pursue them first.

Output a one-line topic statement, e.g.: "형광 프로브 키트 글로벌 시장 규모 2026"

### Step 2: Web Research

Gather sources using your search tools:
- **Deep dive** (for daily/high-priority axes): 8-12 sources via WebSearch + mcp__exa__web_search_exa.
- **Light scan** (for weekly/lower-priority): 3-5 sources.
- For each source, extract the key facts, data points, and claims.
- Store raw search results temporarily in memory (no file needed).

### Step 3: Document Ingest (when a file is provided)

If the user attached a document (PDF, text, URL), ingest it BEFORE the council sees it:
```bash
python3 src/pipeline/muchanipo-ingest.py "{file_path}" \
  --wing {interest_axis} --room {topic_slug} --strategy semantic
```
Then extract ontology (entities + relationships) and store to MemPalace KG:
```
mcp__mempalace__mempalace_kg_add(subject, predicate, object, valid_from=today)
```
Skip this step if no document was provided (web research only).

### Step 4: Council Deliberation

You conduct the council debate by dispatching personas as **parallel Agent subagents with different models**. This ensures genuine multi-perspective analysis (different models produce different reasoning patterns).

**Persona generation — ontology-driven, no fixed cap (MiroFish pattern):**

The number of personas is NOT a fixed number. It is determined by the topic's ontology:

1. **When a document was ingested (Step 3)**: Extract entities from the document's ontology.
   Each entity becomes a persona via the MiroFish `generate_persona_from_entity()` pattern:
   - Individual entities (people, specific orgs) → concrete person personas
   - Group entities (industries, markets, communities) → representative spokesperson personas
   - A 사업계획서 with 30 stakeholders → 30 personas. A simple topic → 5-8 personas.
   - **There is no upper cap.** The document drives the count. 100-200 personas is perfectly fine — sonnet tokens are abundant.

2. **When no document is provided (web research only)**: Generate personas from the topic itself.
   - Identify all relevant stakeholder categories (investors, regulators, users, competitors, scientists, policymakers, farmers, etc.)
   - Create one persona per category. Typically 5-15 depending on topic complexity.

3. **Model assignment**: Use **sonnet for ALL personas** by default. Sonnet is cost-effective and produces quality reasoning. Do NOT use opus for individual personas — save opus for the final synthesis step only.
   - Exception: If a persona requires extremely deep analytical reasoning (e.g., a financial modeler running complex scenarios), use opus for that specific persona.

Example for 사업계획서 분석:
```
온톨로지 추출 → 엔티티 25개 발견:
  - 경희대 (기관) → 주관기관 대변인 (sonnet)
  - 서울대 (기관) → 공동연구 과학자 (sonnet)
  - 농진청 (정부) → 정책 담당관 (sonnet)
  - Erwinia amylovora (병원체) → 식물병리학자 (sonnet)
  - MIRIVA (제품) → 제품 매니저 (sonnet)
  - 사과 농가 (그룹) → 농민 대표 (sonnet)
  - 배 농가 (그룹) → 배 농가 대표 (sonnet)
  - Agdia (경쟁사) → 경쟁사 전략가 (sonnet)
  - 투자자 (그룹) → VC 파트너 (sonnet)
  ... 등등, 엔티티가 있는 만큼 소환
```

**Round 1 -- Independent Analysis (WAVE-based parallel dispatch, ALL sonnet):**

Dispatch personas in waves to prevent hangs. No cap on total personas — ontology drives the count.

- **Wave size**: 12 agents per wave (prevents concurrency saturation + rate limits)
- **Per-agent timeout**: 120 seconds. If an agent doesn't return, mark as TIMED_OUT and skip.
- **Quorum**: 80% of a wave must return before proceeding. If <80%, wait up to 180 seconds total, then proceed with what you have.
- **All use `model="sonnet"`** for cost efficiency.

```
WAVE_SIZE = 12
AGENT_TIMEOUT = 120  # seconds
QUORUM_RATIO = 0.8

for wave in chunks(personas, WAVE_SIZE):
  # Launch wave
  for persona in wave:
    Agent(
      description="Council: {name} ({role})",
      prompt="{persona system prompt}\n\nTopic: {topic}\n\n...",
      model="sonnet",
      run_in_background=true
    )
  # Collect wave results (wait for quorum or deadline)
  # Timed-out agents → logged, excluded from consensus
```

- After ALL waves complete, aggregate results. This IS the multi-agent council — real LLM calls, not role-play.

**Prompt safety guidelines (avoid AUP rejections):**
- NEVER use "attack", "exploit", "impersonate" in persona prompts
- Competitor personas: "분석가로서 객관적으로 평가하라" (NOT "약점을 공격하라")
- Safety/toxicity personas: "추가 검증이 필요한 영역을 식별하라" (NOT "위해성을 평가하라")
- Regulatory personas: "규제 관점에서 분석하라" (NOT "규제기관으로서 판정하라")
- If an agent returns API policy error, log it and skip — do NOT retry with same prompt
- **If >50% of ALL personas timed out**: CRASH-log the experiment, skip to next topic.
- **File-based collection**: All agent results go to JSON files, NOT directly into parent context. Run a compression pass (AAAK format) before Round 2 to prevent context window overflow.

**Round 2 -- Cross-Evaluation:**
- Each persona (sequentially this time, for context) responds to the others' claims.
- Identify agreements, disagreements, and gaps.

**Round 3 (if needed) -- Convergence:**
- Synthesize into consensus + dissent + recommendations.
- Only run if Round 2 has unresolved contradictions.

**Output format**: Build a council report JSON object in memory with these fields:
```json
{
  "council_id": "council-YYYYMMDD-HHMMSS",
  "topic": "topic string",
  "personas": [{"name": "...", "role": "...", "confidence": 0.0-1.0}],
  "consensus": "synthesized consensus text",
  "dissent": "key disagreements",
  "recommendations": ["rec1", "rec2", "rec3"],
  "evidence": ["source1", "source2", ...],
  "confidence": 0.0-1.0
}
```

### Step 5: Evaluation

Score the council output using eval-agent.py. **Self-evaluation is PROHIBITED.** You MUST call the external eval script for objective scoring.

1. Write the council report JSON to a file:
   ```bash
   # Write to .omc/autoresearch/logs/council-report-{timestamp}.json
   ```
2. Run eval-agent.py (MANDATORY):
   ```bash
   python3 src/hitl/eval-agent.py \
     .omc/autoresearch/logs/council-report-{timestamp}.json \
     --rubric config/rubric.json --verbose
   ```
3. Read the output to get verdict + scores.

**If eval-agent.py fails** (file not found, Python error, etc.):
- Log the error in results.tsv with score=0 and description="CRASH: eval-agent.py failed: {error}"
- Do NOT fall back to self-evaluation. Skip this experiment and move to the next topic.

Thresholds: as defined in `config.json` / `rubric.json` (current defaults: PASS >= 28, UNCERTAIN 20-27, FAIL < 20).

### Step 6: Routing

Based on the verdict:

**PASS (keep)**:
1. Write a markdown file to the Obsidian vault using vault-router.py:
   ```bash
   python3 src/hitl/vault-router.py \
     .omc/autoresearch/logs/eval-result-{ts}.json \
     .omc/autoresearch/logs/council-report-{ts}.json
   ```
   OR write directly to the vault path defined in `config.json` for the matching interest axis.
   Read `config.json` → `interest_axes[]` → match by keywords → use that axis's `vault_path`.
   If no axis matches, default to the Feed directory under `identity.vault_path`.
2. Store key facts to MemPalace KG.
3. File format: `YYYY-MM-DD-{topic-slug}.md` with frontmatter (source, date, confidence, council-id) and [[wikilinks]].

**UNCERTAIN (queue for sign-off)**:
1. Save to `.omc/autoresearch/signoff-queue/sq-{timestamp}.json`.
2. Generate HTML report and open in browser:
   ```bash
   python3 src/hitl/signoff-report.py sq-{timestamp} \
     --queue-dir .omc/autoresearch/signoff-queue \
     --reports-dir .omc/autoresearch/reports --open
   ```
3. Auto-trigger Plannotator review for human annotation:
   ```bash
   # If plannotator is available, open annotation UI on the signoff report
   Skill("plannotator:plannotator-annotate", args=".omc/autoresearch/reports/sq-{timestamp}.html")
   ```
   If Plannotator is not available, skip this step silently.
4. Note it in results.tsv. Continue to next topic.

**FAIL (discard)**:
1. Log to `.omc/autoresearch/logs/failed/`.
2. Note it in results.tsv. Continue to next topic.

### Step 7: Log Results

Append one row to `.omc/autoresearch/results.tsv` (tab-separated):

```
timestamp	topic	axis	verdict	score	description
```

- timestamp: ISO format YYYY-MM-DD HH:MM
- topic: the research topic
- axis: which interest axis (neobio, ai_ml, business, tech_stack)
- verdict: PASS, UNCERTAIN, or FAIL
- score: total out of 40 (0 for crashes/skips)
- description: one-line summary of what was found

Example:
```
2026-04-09 14:30	형광 프로브 시장 2026	neobio	PASS	32	글로벌 시장 $2.1B, CAGR 8.3%, 아시아 성장 주도
2026-04-09 14:45	LangGraph vs CrewAI	ai_ml	UNCERTAIN	25	기능 비교 완료, 벤치마크 데이터 부족으로 sign-off 대기
2026-04-09 15:00	React Native 0.80	tech_stack	FAIL	18	공식 릴리스 전이라 신뢰할 수 있는 소스 부족
```

## The Experiment Loop

LOOP FOREVER:

1. Look at results.tsv: what topics have been done, what axes need attention.
2. Select the next topic per Step 1 rules.
3. Research it per Step 2.
4. If a document was provided, ingest it per Step 3.
5. Run council debate per Step 4.
6. Evaluate per Step 5.
7. Route the result per Step 6 (PASS -> vault, UNCERTAIN -> queue, FAIL -> discard).
8. Log to results.tsv per Step 7.
9. Brief cooldown: take stock of what you learned, note any follow-up questions for next cycle.
10. GOTO 1.

**Crashes**: If a step fails (web search timeout, MemPalace offline, file write error, agent timeout), log the error in results.tsv with score=0 and description="CRASH: {reason}", then skip to the next topic. Do NOT stop the loop.

**Circuit Breaker**: If 5 consecutive experiments result in FAIL or CRASH, PAUSE the loop. Log "CIRCUIT BREAKER: 5 consecutive failures. Switching to a different interest axis or waiting for human input." Try a completely different axis. If all axes have been tried and still fail, pause for 10 minutes then retry.

**Web Search Retry Limit**: If 3 consecutive web searches fail in Step 2 (timeout or empty), skip to Step 4 with whatever sources you have. Do not keep retrying.

**results.tsv Write Failure**: If results.tsv cannot be written, log to `.omc/autoresearch/logs/emergency-log.txt` as fallback. If that also fails, print to stderr and continue.

**results.tsv Rotation**: When results.tsv exceeds 500 rows, archive as `results-{date}.tsv` and keep only the last 100 rows in active file.

**NEVER STOP**: Once the experiment loop has begun (after the initial setup), do NOT pause to ask the human if you should continue. Do NOT ask "should I keep going?" or "is this a good stopping point?". The human might be asleep, or gone from their computer and expects you to continue working *indefinitely* until you are manually stopped. You are autonomous. If you run out of topics, cycle back through the interest axes with new angles -- combine keywords across axes, explore tangential areas, follow up on previous UNCERTAIN results with deeper research. The loop runs until the human interrupts you, period.

## Two Modes

### Mode 1: Autonomous Loop
```
User: "오토리서치 시작" or "세컨드 브레인 돌려"
-> Setup -> Loop forever through interest axes
```

### Mode 2: Targeted Research
```
User: "이 논문 분석해줘" [attachment] or "MIRIVA 경쟁사 분석해줘"
-> Setup -> Ingest document -> One research cycle on specified topic -> Report to user -> STOP
```
In targeted mode, you run exactly ONE cycle and report back. No infinite loop.

## Helper Scripts Reference

Scripts live in `src/hitl/` and `src/pipeline/`. Call via `Bash: python3 src/hitl/{script}` or `src/pipeline/{script}`:

| Script | Purpose | When to use |
|--------|---------|-------------|
| `session-check.py` | Check pending sign-offs, recent activity | Setup step 3 |
| `muchanipo-ingest.py <file> --wing X --room Y` | Chunk + store document to MemPalace | Step 3 (document provided) |
| `eval-agent.py <report.json> --rubric rubric.json` | Score council output | Step 5 Option A |
| `vault-router.py <eval.json> <report.json>` | Route to vault/queue/discard | Step 6 |
| `signoff-queue.py list` | List pending human reviews | On-demand |
| `signoff-queue.py approve <id>` | Approve a queued item | On-demand |

## State Files

```
.omc/autoresearch/
  program.md              # Interest axes, rubric, vault structure (human edits)
  config.json             # Structured config parsed from program.md
  rubric.json             # Scoring rules
  results.tsv             # Experiment log (this file is YOUR lab notebook)
  logs/                   # Council reports, eval results, errors
  signoff-queue/          # UNCERTAIN items awaiting human review
  wiki/log.md             # Append-only operation log
  wiki/index.md           # Auto-maintained page index
```

## Constraints

- NEVER store speculative information as fact
- NEVER modify existing vault notes without clear justification
- NEVER exceed 5 council rounds per topic (escalate instead)
- ALWAYS include source attribution
- ALWAYS check for contradictions with existing vault knowledge
- ALWAYS log every research attempt (success or failure) to results.tsv
