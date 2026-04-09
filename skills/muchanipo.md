---
name: muchanipo
description: 완전 자율 세컨드 브레인 엔진. Karpathy Autoresearch + LLM Council + MiroFish 패턴. 문서 인제스트 → 페르소나 토론 → Eval → Obsidian vault 확장.
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
  - Glob
  - Grep
  - Bash
  - Agent
  - WebSearch
  - WebFetch
  - mcp__exa__web_search_exa
  - mcp__exa__crawling_exa
  - mcp__context7__resolve-library-id
  - mcp__context7__query-docs
---

# MuchaNipo — Autonomous Second Brain Engine

Inspired by Karpathy's Autoresearch + LLM Council + MiroFish crowd simulation.
An infinite research loop that continuously expands your personal ontology
through multi-persona council deliberation with full document ingestion.

## Trigger Keywords
- "muchanipo", "무차니포", "자율 리서치", "세컨드 브레인", "second brain"
- "리서치 돌려", "오토리서치"
- When a document is attached with research intent

## Two Modes

### Mode 1: Autonomous Loop (program.md driven)
```
User: "오토리서치 시작" or "세컨드 브레인 돌려"
→ Reads program.md → selects topic → researches → council → eval → vault → repeat
```

### Mode 2: Targeted Research (user-directed)
```
User: "이 논문 분석해줘" [attachment] or "MIRIVA 경쟁사 분석해줘"
→ Document Ingest → MemPalace KG → council (with search access) → eval → vault
```

## Architecture: Agent Swarm

```
┌───────────────────────────────────────────────────────┐
│              ORCHESTRATOR (this skill)                  │
│                                                         │
│  ┌───────────┐    ┌────────────┐    ┌──────────────┐   │
│  │ Researcher │───▶│  Document  │───▶│   Persona    │   │
│  │   Agent    │    │  Ingestor  │    │  Generator   │   │
│  └───────────┘    └──────┬─────┘    └──────┬───────┘   │
│                          │                  │           │
│                   ┌──────▼──────┐    ┌──────▼───────┐   │
│                   │  MemPalace  │◀──▶│   Council    │   │
│                   │  KG + Palace│    │   Engine     │   │
│                   └──────┬──────┘    └──────┬───────┘   │
│                          │                  │           │
│                   ┌──────▼──────┐    ┌──────▼───────┐   │
│                   │  Obsidian   │◀───│    Eval      │   │
│                   │   Vault     │    │    Agent     │   │
│                   └─────────────┘    └──────────────┘   │
│                                                         │
│  Shared State: MemPalace (KG + Palace + AAAK + Chunks)  │
│  Config: .omc/autoresearch/program.md                    │
│  Logs: .omc/autoresearch/logs/                           │
│  Sign-off: .omc/autoresearch/signoff-queue/              │
└───────────────────────────────────────────────────────┘
```

## Document Ingest Pipeline (MiroFish Pattern)

When a document (PDF, text, URL) is provided, it goes through full ingestion
BEFORE the Council sees it. This ensures zero information loss.

### Ingest Step 1: Text Extraction & Chunking
```
Input: PDF / text / URL
  ↓
TextProcessor:
  - Extract text (Read tool for PDF, WebFetch for URL)
  - Preprocess: normalize whitespace, standardize newlines
  - Split into 500-character chunks with 50-char overlap
  - Store chunks count and metadata
Output: List[str] chunks (500 chars each)
```

### Ingest Step 2: Ontology Generation (LLM-powered)
```
Input: Full text (up to 50,000 chars) + research context
  ↓
OntologyGenerator (via LLM):
  - Analyze document to identify key entity types (up to 10)
  - Extract relationship types between entities (6-10)
  - Entity examples: Person, Organization, Technology, Institution,
    Product, Regulation, Disease, Region, etc.
  - Relationship examples: DEVELOPS, REGULATES, COMPETES_WITH,
    TREATS, FUNDS, PARTNERS_WITH, etc.
Output: ontology.json {entity_types: [...], edge_types: [...]}
```

### Ingest Step 3: MemPalace Storage
```
Input: chunks + ontology
  ↓
For each chunk:
  1. mempalace_add_drawer(content=chunk, wing=topic_wing, room=topic_room)
  2. mempalace_kg_add(subject, predicate, object, valid_from=now)
     → Extract entities and relationships from each chunk
  ↓
Output: 
  - All chunks stored as searchable drawers
  - Knowledge graph populated with entities + relationships
  - Council can now query ANY part of the document via mempalace_search
```

### Why This Matters
```
BEFORE (information loss):
  [20-page PDF] → [Claude reads] → [Summary ~500 words] → [Council debates summary]
  Problem: Council never sees budget tables, specific dates, technical specs

AFTER (zero loss, MiroFish pattern):
  [20-page PDF] → [40 chunks × 500 chars] → [MemPalace KG]
                                                    ↑
  [Council persona asks: "예산 구조가 어떻게 되나?"]
  → mempalace_search("예산 사업비 권역별") → returns exact chunks with numbers
  → Council debates with FULL access to original data
```

## Execution Flow

### Step 0: Initialize
```
1. Read .omc/autoresearch/program.md (config)
2. Read .omc/autoresearch/config.json (structured config)
3. Check MemPalace status (mempalace status)
4. Load recent research logs to avoid repeats
5. Check sign-off queue for pending items → notify user if any
6. Concurrency guard: check .omc/autoresearch/.lock
   - If exists and PID is alive → abort ("이미 실행 중입니다")
   - If exists but PID dead → remove stale lock, proceed
   - If not exists → create lock with current session info
7. On exit (normal or error): remove .lock file
```

### Step 0.5: Document Ingest (when document provided)

If a document (PDF, text, URL) is provided:
```
1. Run ingest script:
   Bash: .omc/autoresearch/mp-env/bin/python .omc/autoresearch/muchanipo-ingest.py \
     --wing {interest_axis} --room {topic_slug} \
     --strategy semantic \
     "{file_path}"

2. Ontology extraction (Claude does this after ingest):
   - Read the document (first 50,000 chars)
   - Extract entity types (up to 10): Person, Organization, Technology, etc.
   - Extract relationship types (6-10): DEVELOPS, REGULATES, COMPETES_WITH, etc.
   - Save to .omc/autoresearch/logs/ontology-{timestamp}.json

3. Generate KG triples from ontology:
   - For each entity found, create MemPalace KG entry:
     mempalace_kg_add(subject, predicate, object, valid_from=today)

4. Pass ingest metadata to Council:
   - wing and room where chunks are stored
   - ontology.json path for entity reference
   - Total chunks count for search scope awareness
```

### Step 1: Topic Selection (Researcher Agent)

**Autonomous mode:**
```
Agent(
  subagent_type="arc-researcher",
  prompt="Read program.md, check recent logs, select next topic. Return research brief.",
  model="sonnet"
)
```

**Targeted mode:**
```
# User provided topic or document
research_brief = {
  "topic": user_topic_or_doc_summary,
  "source": "user_input",
  "depth": "deep_dive"
}
```

### Step 2: Persona Generation

```
Agent(
  subagent_type="persona-generator",
  prompt=f"Generate personas for this topic: {research_brief.topic}\n\nContext: {research_brief.synthesis}",
  model="sonnet"
)
→ Returns 3-7 personas as JSON
```

### Step 3: Council Deliberation

```
# Invoke the council skill with personas AND ingest metadata
Skill("arc-council", args=f"""
Topic: {research_brief.topic}
Personas: {personas_json}

## Document Access (MemPalace)
Ingested documents are in MemPalace:
  Wing: {ingest_wing}
  Room: {ingest_room}
  Chunks: {chunk_count} chunks from {file_count} documents
  Ontology: {ontology_path}

IMPORTANT: Do NOT use summaries. Personas must use mempalace_search
to find specific facts from the original documents during debate.
""")
→ Returns council report with consensus, dissent, recommendations
```

### Step 4: Evaluation

```
Agent(
  subagent_type="arc-evaluator",
  prompt=f"Evaluate this council output:\n{council_report}",
  model="sonnet"
)
→ Returns: PASS / UNCERTAIN / FAIL with scores
```

**Routing:**
- **PASS** → Step 5 (Wiki storage)
- **UNCERTAIN** → Save to signoff-queue, notify user, continue loop
- **FAIL** → Log failure, skip to next topic

### Step 5: Wiki Storage

```
Agent(
  subagent_type="arc-wiki",
  prompt=f"""Store this approved research to Obsidian vault:
  Topic: {topic}
  Council Report: {council_report}
  Eval: {eval_report}
  Interest Axis: {interest_axis}
  """,
  model="sonnet"
)
→ Creates/updates Obsidian notes with wikilinks
→ Stores to MemPalace drawer
→ Updates KG with temporal triples
```

### Step 6: Loop Control

```
# Log completion
append_log({
  "timestamp": now(),
  "topic": topic,
  "verdict": eval_verdict,
  "council_rounds": N,
  "consensus": confidence,
  "vault_path": saved_path
})

# Check loop conditions
IF mode == "autonomous":
  wait(cooldown_seconds)  # 30s default
  GOTO Step 1  # NEVER STOP
ELIF mode == "targeted":
  report_to_user(summary)
  STOP
```

## Sign-off Queue Management

When user starts a new session, check for pending sign-offs:

```
pending = glob(".omc/autoresearch/signoff-queue/*.json")
IF pending:
  notify(f"승인 대기 {len(pending)}건이 있습니다.")
  for each pending:
    show_summary()
    ask: approve / reject / modify
    record_decision_to_rubric_feedback()
```

## State Persistence

All state stored in `.omc/autoresearch/`:
```
.omc/autoresearch/
├── program.md              # Configuration (Software 3.0)
├── config.json             # Structured config
├── logs/                   # Research logs (topic, verdict, timestamp)
│   ├── research-{ts}.json  # Per-research log
│   └── failed/             # Failed evaluations
├── council-logs/           # Full council debate logs
│   └── council-{id}/       # Per-session logs
├── signoff-queue/          # Pending human review
│   └── {ts}-{topic}.json   # Queued items
├── rubric-feedback.jsonl   # Human sign-off decisions (for rubric evolution)
└── rubric-history/         # Rubric version history
```

## Error Handling

| Error | Action |
|-------|--------|
| Web search fails | Continue with available data, note gaps in council brief |
| Codex/OpenCode timeout | Fallback to Claude-only council (see arc-council fallback) |
| MemPalace unavailable | Store to vault directly, queue MemPalace sync for later |
| Vault write fails | Retry once, then save to .omc/autoresearch/orphaned/ |
| All retries exhausted | Log error, notify user, skip topic, continue loop |

## Usage Examples

### Autonomous mode
```
User: "오토리서치 시작"
→ Reads program.md
→ Selects: "형광 프로브 시장 2026 동향" (NeoBio axis, deep, daily)
→ Researches → 5 personas generated → 3-round council → PASS (score: 32)
→ Saved to ~/Documents/Hyunjun/Neobio/2026-04-08-fluorescent-probe-market.md
→ Next topic: "LangGraph vs CrewAI 비교" (AI/ML axis, deep, daily)
→ ... continues indefinitely
```

### Targeted mode
```
User: "이 사업계획서 분석해줘" [attaches PDF]
→ Extracts key content from PDF
→ 6 personas: 투자자, 규제전문가, 경쟁사CEO, 기술CTO, 고객대표, 시장분석가
→ 4-round council → UNCERTAIN (score: 25)
→ Queued for sign-off with detailed report
→ User reviews: "승인, 하지만 규제 부분 더 조사해줘"
→ Follow-up research triggered on regulatory aspects
```

### Sign-off review
```
User: (starts new session)
→ "승인 대기 2건이 있습니다."
→ 1. 형광 프로브 규제 변화 (score: 24, UNCERTAIN)
→ 2. React Native 0.80 마이그레이션 (score: 22, UNCERTAIN)
→ User: "1번 승인, 2번은 Flutter 비교도 추가해줘"
→ 1 stored to vault, 2 queued for follow-up research
```

## Constraints
- NEVER store speculative information as fact
- NEVER modify existing vault notes without clear justification
- NEVER exceed 5 council rounds (escalate instead)
- ALWAYS include source attribution
- ALWAYS check for contradictions with existing vault knowledge
- ALWAYS log every research attempt (success or failure)
