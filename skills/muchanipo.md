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

## Policy Decisions (C29 hybrid — issue #9 resolution)

이 4 정책은 skills/muchanipo.md의 다른 섹션 + muchanipo.md(root)에서 단일 SoT로 사용한다.
충돌 시 항상 이 섹션이 우선.

### ① Self-Evaluation — Hybrid
- **Default**: `eval-agent.py` 외부 sub-agent로 점수 (PROHIBITED self-eval).
- **Fallback**: eval-agent 호출 실패 시(예: rate limit) → Claude 자체 평가 OK,
  단 결과에 `"eval_mode": "self_fallback"` 명시 + 다음 cycle에서 재평가 큐 등록.

### ② Orchestrator — Two-tier
- **High-level control flow**: Claude (이 skill 내부 reasoning).
- **Mechanical steps** (lock acquisition, file IO, subprocess): `src/runtime/orchestrator.py`
  같은 deterministic Python 헬퍼.
- "You ARE the orchestrator"는 **high-level만**. orchestrator.py는 helper 역할.

### ③ Council — Hybrid
- **Round 1**: 26 페르소나 차례로 plays (cross-influence 차단, 독립 의견).
- **Round 2+**: parallel sub-agent (다른 의견 보면서 토론).
- 즉 "you are council" + "parallel Agent" 둘 다 옳다 — round 단계에 따라 다름.

### ④ Loop — Pause + Notify (NEVER STOP의 안전망)
- **Default**: NEVER STOP — 인간 interrupt까지 무한 cycle.
- **Exception**: 5회 연속 council UNCERTAIN+FAIL → 자동 PAUSE + 사람에게 알림
  (예: state file `.omc/autoresearch/circuit-breaker.json`에 기록).
- PAUSE 상태에서 사람이 resume 명령(or 토픽 변경) 시 cycle 재개.

---

## Execution Independence

MuchaNipo runs **completely independent** of OMC autopilot/ralph/ultrawork modes.
- State files: ONLY `.omc/autoresearch/` — never read or write `.omc/state/autopilot-state.json` or any other OMC mode state.
- If OMC autopilot is running concurrently, ignore it. MuchaNipo has its own loop.
- Do NOT check for or respect `cancel` signals from OMC modes. MuchaNipo stops only when the human interrupts.

## Silent Mode

When the user says "silent", "조용히", or "SILENT MODE", minimize terminal output:
- Each experiment: output ONLY one line: `[EXP#{N}] {topic} → {verdict} {score}/{max_score}`
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

5. **Read progress.md (accumulated learnings from all past loops)**:
   - Read `.omc/autoresearch/progress.md` — this is the **lesson log**. Past mistakes, insights, follow-up questions.
   - This prevents context rot: you won't repeat Exp#5's mistake if you read "한국 AgTech은 한국어로 검색해야 함."
   
6. **Load results.tsv** (last 50 lines only, NOT the full file): Check recent topics to avoid repetition.
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
- Update `_muchanipo/index.md` — add one line: `- [[{vault-filename}]] — {one-line summary} ({score}/{max_score})`
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

**The goal is simple: produce the highest-quality knowledge entries for Hyunjun's Obsidian vault.** Quality is measured by the eval rubric (10 axes, each 0-10, total out of 100). Aim for PASS (>= 70). UNCERTAIN (50-69) gets queued for human sign-off. FAIL (< 50) gets discarded.

**Simplicity criterion**: A deep insight with 3 solid sources beats a sprawling report with 12 weak ones. Prefer depth over breadth. If a topic is too broad, narrow it down before researching.

**The first run**: Your very first cycle should be a straightforward topic from the highest-priority interest axis to establish the baseline workflow.

## The Research Cycle (one experiment)

### Step 0: Interactive Intent Interview (사용자 리서치 요청 시 — gstack /office-hours 차용, C21)

**사용자가 리서치 요청을 던진 모든 경우** 적용 (Mode 1 trigger 키워드 "오토리서치 시작"/"세컨드 브레인 돌려" 제외 — 이 trigger는 곧장 자율 무한 루프). 이 phase에서 **Claude이 직접 사용자와 대화**하며 의도를 정밀화하고, 끝에서 **Mode 1/Mode 2를 자동 라우팅**한다.

**Phase 0a — Quick Triage + Type 분류**
- `src/intent/interview_prompts.py` `assess(user_input)` → InterviewPlan(mode, missing_dimensions, **research_type**)
- 입력이 짧고 모호하거나 핵심 차원(timeframe/domain/evaluation) 부족 → `mode="deep"`
- 입력이 풍부하면(차원 3+) → `mode="quick"`
- `research_type`: `exploratory | comparative | analytical | predictive` (deep-research-query Phase 1 차용)

**Phase 0b — Interactive Interview v2** ⭐ (Adaptive, AskUserQuestion 도구 직접 호출)

흐름:
1. **Pre-screen** (`office_hours.pre_screen_hook(topic, history)`) — 영문 미지 약어/줄임말 감지 시 1회 명확화. `AskUserQuestion`으로 짧게 묻고 답변 받은 뒤 본 인터뷰 진입. (LangChain ODR "ABSOLUTELY NECESSARY" 원칙 — 1회 초과 금지)
2. **Rubric 생성** (`InterviewRubric(topic=user_input)`) — 6 RubricItem(Q1~Q6) 자동 생성. `coverage_status=NOT_ASKED`, `entropy_estimate=1.0`.
3. **루프 (최대 6 round)**:
   - `select_next_question(rubric)` → 미답변 차원 중 **entropy 최대** 항목 (arXiv 2510.27410 greedy)
   - `reframe_with_context(dim_id, topic, prev_answers)` → 토픽-맞춤 question text + 4개 선택지 + Other (LLMREI Cookbook)
   - `AskUserQuestion` 도구 호출 — 헤더에 `[N/6]` progress 표시
   - 답변 수신 → `rubric.update(dim_id, answer, quality_score)` (Other 입력=0.6 / 옵션 선택=0.9 휴리스틱)
   - `rubric.is_complete(threshold=0.75)` AND `coverage_rate ≥ 0.75` → **조기 종료** (2601.14798 동적 stop)
4. 답변 통합 `merge_answers_to_text(user_input, qa_pairs)` → Phase 0c 진입.

**Quick mode**는 위 루프를 `missing_dimensions`만 대상으로 1-2 round 단축.

**Phase 0c — DesignDoc 생성 + 사용자 review**
- `OfficeHours().reframe(merged_text)` → DesignDoc
- `format_designdoc_review(design_doc)` 출력 (한 페이지 markdown)
- 사용자 ✅ 승인 / ✏️ 수정(해당 섹션 재질문) / ❌ Interview부터 다시
- lockdown.aup_risk + redact 자동 통과

**Phase 0d — Coverage Gate + ConsensusPlan 생성 + 사용자 review**
- **Coverage Gate**: `plan_review.rubric_coverage_gate(rubric, threshold=0.75)` → 미충족 시 부족 차원 1개 보완 probe (`AskUserQuestion` 1회 추가) 후 재진입 (Anthropic Interviewer planning→analysis 패턴)
- `PlanReview().autoplan(design_doc)` → ConsensusPlan (CEO mode / Eng feasibility / Design journey / Devex friction)
- `format_consensusplan_review(plan)` 출력
- gate 실패(consensus < 0.6 / aup_risk > 0.7 / feasibility=blocked) 시 자동 차단 + 추가 질문
- 사용자 ✅ 시작 / ✏️ 수정 / ❌ DesignDoc부터 다시

**Phase 0e — Mode Routing (자동 결정)** ⭐
- `route_mode(design_doc, consensus_plan, user_input, qa_text)` → ModeDecision
- 휴리스틱:
  - "지속/장기/매일/쌓아" 키워드 + ceo.mode="expansion" + alternatives 다수 → `autonomous_loop` (Mode 1)
  - "이번 한 번/지금/결과 받기" 키워드 + ceo.mode="hold"/"reduction" → `targeted_iterative` (Mode 2)
  - 신호 균형 또는 약함 → default `targeted_iterative` (저비용 안전 진입)
- `format_mode_routing_decision(decision)` 한 줄 보고 + 사용자 ✅ / ✏️ 다른 모드로
- 결정된 mode에 따라 Step 1 또는 Mode 1 loop 진입

**Phase 0 종료 시**:
- `ConsensusPlan.to_ontology()` → Step 4 council ontology 직접 입력 (roles + intents + value_axes(C16) + design_doc_brief)
- Korean domain 자동 감지 → `agtech_farmer` role + `KoreaPersonaSampler.agtech_farmer_seed(n)` 자동 호출
- decision.mode == "autonomous_loop" → Mode 1 무한 loop / "targeted_iterative" → Mode 2 10라운드

**Mode 1 직접 trigger 키워드** ("오토리서치 시작" / "세컨드 브레인 돌려")는 Phase 0 전체 skip — 사용자가 명시적으로 자율 누적을 원하는 의도.

### Step 1: Topic Selection

Select the next topic based on program.md interest axes:
- Rotate through axes proportionally: deep=3x frequency, moderate=1x.
- Check results.tsv to avoid recently researched topics.
- Prefer topics that cross 2+ interest axes (higher novelty).
- If previous research opened new questions, pursue them first.
- **Mode 2면**: Step 0의 ConsensusPlan.intents가 이 단계를 대체. Topic = `design_doc.raw_input`.

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
python3 src/ingest/muchanipo-ingest.py "{file_path}" \
  --wing {interest_axis} --room {topic_slug} --strategy semantic
```
Then extract ontology (entities + relationships) and store to MemPalace KG:
```
mcp__mempalace__mempalace_kg_add(subject, predicate, object, valid_from=today)
```
Skip this step if no document was provided (web research only).

### Step 3.5: Ontology Co-Generation (Claude + Codex)

온톨로지 추출을 단일 모델이 아닌 **Claude + Codex CLI 병렬 추출 후 합집합 병합**으로 수행한다. 서로 다른 모델의 사고 패턴이 서로 다른 이해관계자를 발견한다.

```
[Document]
  ├──→ Claude (Agent, sonnet): 3-Layer 온톨로지 추출
  └──→ Codex CLI (gpt-5.4-codex): 독립적 온톨로지 추출
           ↓                            ↓
      Claude 엔티티 Set A         Codex 엔티티 Set B
           └──────────┬─────────────┘
                 Merge: union(A, B) + dedup by role
                      ↓
                합산 엔티티 (A∪B)
                (Claude-only + 공통 + Codex-only)
                      ↓
                페르소나 생성 → Council 디스패치
```

**실행 방법:**

1. **Claude 추출** (Agent, sonnet, background):
   ```
   Agent(prompt="이 문서를 읽고 3-Layer 온톨로지를 추출하라. Layer 1: 문서 내부 엔티티, Layer 2: 외부 직접 이해관계자, Layer 3: 교차도메인. 각 엔티티마다 name, type, layer, role_description을 JSON 배열로 출력.", model="sonnet")
   ```

2. **Codex 추출** (codex exec, parallel):
   ```bash
   no_proxy='*' codex exec --full-auto -m gpt-5.4-codex \
     "Read {file_path}. Extract a multi-layer stakeholder ontology:
      Layer 1: entities explicitly in the document.
      Layer 2: external direct stakeholders (supply chain, regulators, international).
      Layer 3: cross-domain experts (adjacent industries, contrarians, societal).
      Output JSON array: [{name, type, layer, role_description}].
      Save to {output_path}/ontology-codex.json"
   ```

3. **병합** (Claude orchestrator):
   - 두 결과를 읽고 role_description 유사도로 중복 제거
   - 합집합 = 최종 온톨로지
   - 각 엔티티 → 페르소나 생성 (source 필드에 "claude", "codex", "both" 표시)

**Fallback**: Codex CLI 사용 불가 시 Claude 단독 추출. 이 경우에도 반드시 3-Layer를 명시적으로 요청.

### Step 4: Council Deliberation

You conduct the council debate by dispatching personas as **parallel Agent subagents with different models**. This ensures genuine multi-perspective analysis (different models produce different reasoning patterns).

**Persona generation — multi-layer ontology, no fixed cap (MiroFish pattern):**

The number of personas is NOT a fixed number. It is determined by the topic's **full ecosystem ontology** — NOT limited to entities mentioned in the document.

**3-Layer Ontology Extraction (MiroFish multi-layer pattern):**

1. **Layer 1 — Document entities (내부)**: Extract entities explicitly mentioned in the document.
   - Individual entities (people, specific orgs) → concrete role personas
   - Group entities (industries, markets, communities) → representative spokesperson personas

2. **Layer 2 — Ecosystem entities (외부 직접)**: Identify stakeholders NOT in the document but directly affected by or involved in the topic.
   - Supply chain: 원료 공급자, 제조 파트너, 유통 채널
   - Regulatory: 관련 법령 소관 부처, 인증 기관
   - International: 해외 유사 시장 참여자, 수출입 관계자
   - End-user edge cases: 비전형적 사용자, 극단적 사용 환경

3. **Layer 3 — Cross-domain entities (외부 간접)**: Bring in perspectives from adjacent industries or disciplines that offer unexpected insights.
   - Adjacent tech: 유사 기술을 다른 분야에 적용한 사례 전문가
   - Academic: 핵심 과학 원리의 기초연구자
   - Contrarian: 기술 회의론자, 대안 기술 옹호자
   - Societal: 환경, 윤리, 소비자, 보험, 법률 관점

**Rule**: Layer 1이 전체 페르소나의 40-50%, Layer 2가 30-35%, Layer 3이 15-25%. Layer 3이 없으면 진짜 다관점이 아니라 이해관계자 설문에 불과하다.

**There is no upper cap.** Ontology가 30개 엔티티를 발견하면 30개 페르소나. 100-200도 가능 — sonnet 토큰은 풍부하다.

4. **Model assignment**: Use **sonnet for ALL personas** by default. Sonnet is cost-effective and produces quality reasoning. Do NOT use opus for individual personas — save opus for the final synthesis step only.
   - Exception: If a persona requires extremely deep analytical reasoning (e.g., a financial modeler running complex scenarios), use opus for that specific persona.

Example for 사업계획서 분석:
```
Layer 1 (문서 내부 엔티티):
  - 주관기관 (기관) → 사업총괄 관점 (sonnet)
  - 공동연구기관 (기관) → 실증연구 과학자 (sonnet)
  - 농정기관 (정부) → 정책 담당관 (sonnet)
  - 검출 대상 미생물 (기술) → 진단기술 전문가 (sonnet)
  - 실증제품 (제품) → 제품 매니저 (sonnet)
  - 과수 농가 (그룹) → 농민 대표 (sonnet)
  - 경쟁제품 (경쟁사) → 시장 분석가 (sonnet)

Layer 2 (외부 직접 이해관계자):
  - 화학 원료 공급사 → 공급망 전문가 (sonnet)
  - 수출검역 당국(USDA/EFSA) → 국제 검역관 (sonnet)
  - 농작물 재해보험사 → 보험 리스크 분석가 (sonnet)
  - UV LED 하드웨어 제조사 → 광학 엔지니어 (sonnet)

Layer 3 (교차 도메인):
  - 의료 현장진단(POCT) 전문가 → 유사 기술 다른 산업 적용 (sonnet)
  - 환경단체 → 화학물질 야외 방출 관점 (sonnet)
  - 농업경제학자 → 기술 채택 곡선/확산 모델 (sonnet)
  - 제조물책임(PL) 법률가 → 법적 리스크 (sonnet)
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

**Document-scope constraint (분석 범위 vs 페르소나 범위 구분):**

온톨로지 추출(=누구를 소환할지)과 분석 범위(=무엇을 평가할지)는 별개다:

- **페르소나 소환 범위 = 제한 없음**: 3-Layer 온톨로지에 따라 문서 밖 이해관계자도 자유롭게 소환. Layer 3 교차도메인 전문가가 진짜 다관점을 만든다.
- **분석 범위 = 문서 기반 + 외부 전문지식 활용**: 각 페르소나는 자신의 전문 지식으로 문서를 평가한다. 단, 문서에 명시되지 않은 사실을 문서에 있는 것처럼 인용하면 안 된다. 문서에 없는 사항은 "문서에서 다루지 않음 — 이 관점에서는 {X}가 필요하다"로 표시.
- Persona prompt에 포함할 문구:
  "이 문서를 당신의 전문 관점에서 평가하세요. 당신의 도메인 지식을 활용하여 문서의 주장을 검증하되, 문서에 없는 정보를 문서 내용인 것처럼 인용하지 마세요. 문서가 다루지 않은 중요 사항은 '문서 미비점'으로 명시하세요."

**Prompt safety guidelines (avoid AUP rejections):**

AUP 거부는 페르소나 손실 = 관점 손실. 거부율 0%를 목표로 프롬프트를 설계한다.

- **실명 금지**: 실제 교수/연구자 이름을 페르소나 신원에 직접 쓰지 않는다.
  - BAD: "당신은 서울대 오창식 교수입니다"
  - GOOD: "당신은 식물 관련 학과의 부교수급 연구자입니다"
- **병원체/세균 직접 언급 최소화**: 특정 병원체명은 "검출 대상 미생물", "표적 균주"로 대체.
  - BAD: "Erwinia amylovora의 감염 메커니즘을 분석하라"
  - GOOD: "진단 기술이 표적 미생물을 정확히 식별하는 메커니즘을 평가하라"
- **"역할 수행" 대신 "관점 제공"**: impersonation 느낌을 줄인다.
  - BAD: "당신은 농림축산검역본부 관계자로서 판정하라"
  - GOOD: "방역정책 관점에서 이 기술의 제도적 편입 가능성을 분석하라"
- **위험 동사 차단 목록**: attack, exploit, impersonate, hack, sabotage, weaponize, infect, contaminate, spread disease, poison, toxic exposure
- **AUP 고위험 조합 패턴** (단독은 OK, 조합 시 거부됨):
  - 실명 + 병원체/세균 분석 → 거부 (Round 1 식물병리학자 사례)
  - 독성학 + 화학물질 + 환경 방출 + 오염 → 거부 (Round 2 환경안전 분석가 사례)
  - 생물학적 위해 + 안전성 평가 + 작업자 노출 → 고위험
- **안전 대체어 목록**:
  - "위해성 평가" → "추가 검증이 필요한 영역 식별"
  - "약점 공격" → "개선이 필요한 측면을 객관적으로 분석"
  - "규제기관으로서 판정" → "규제 관점에서 요건 충족 여부 분석"
  - "병원체 검출" → "진단 대상 미생물 검출"
  - "감염 경로" → "전파 경로" 또는 "확산 동선"
  - "환경독성학" → "환경영향 분석"
  - "화학물질 오염/독성" → "화학 성분의 환경 잔류 특성 분석"
  - "작업자 노출 위험" → "사용자 안전 요건 검토"
  - "토양/수계 오염" → "토양/수계 잔류 가능성 검토"
- **환경/안전 페르소나 프레이밍**:
  - BAD: "환경독성학자로서 화학물질 방출의 오염 리스크를 평가하라"
  - GOOD: "제품 안전성 분석가로서, 이 진단 도구의 야외 사용 시 환경영향과 사용자 안전 요건을 검토하라"
- Competitor personas: "분석가로서 객관적으로 평가하라" (NOT "약점을 공격하라")
- If an agent returns API policy error:
  1. Log the error with the triggering prompt's key phrases
  2. Rephrase using the 안전 대체어 and retry ONCE
  3. If retry also fails, skip and log — do NOT retry a third time
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

Score the council output using eval-agent.py. **Self-evaluation is PROHIBITED by default** — call external eval script. Self-eval fallback only as defined in **Policy Decisions ①** (eval-agent unavailable).

1. Write the council report JSON to a file:
   ```bash
   # Write to .omc/autoresearch/logs/council-report-{timestamp}.json
   ```
2. Run eval-agent.py (MANDATORY):
   ```bash
   python3 src/eval/eval-agent.py \
     .omc/autoresearch/logs/council-report-{timestamp}.json \
     --rubric config/rubric.json --verbose
   ```
3. Read the output to get verdict + scores.

**If eval-agent.py fails** (file not found, Python error, etc.):
- Log the error in results.tsv with score=0 and description="CRASH: eval-agent.py failed: {error}"
- Do NOT fall back to self-evaluation. Skip this experiment and move to the next topic.

Thresholds: as defined in `config.json` / `rubric.json` (v2.0 defaults: PASS >= 70, UNCERTAIN 50-69, FAIL < 50 on 100-point scale; v2.1+ when `citation_fidelity` 11번째 축 활성화 시 thresholds 재조정).

**Grounding gate (v2.1, narrow C1)**: If `grounding_gate.enabled` is true and the natural verdict is `PASS`, the citation grounding pass runs after eval-agent verdict. If `verified_claim_ratio < min_verified_ratio` or `unsupported_critical_claim_count > max_critical_unsupported`, verdict is demoted to `UNCERTAIN` with reason logged. The `citation_fidelity` axis itself is weight 0 in v2.1 (측정만 누적, 점수 무영향) — gate 는 점수 보너스가 아니라 PASS 차단으로만 작동한다. Gate 결정은 `lockdown.audit_log` 로 추적된다.

### Step 6: Routing

Based on the verdict:

**ALL VERDICTS — always generate HTML report first:**
```bash
python3 src/hitl/signoff-report.py {council-id} \
  --queue-dir .omc/autoresearch/signoff-queue \
  --reports-dir .omc/autoresearch/reports --open
```
This opens the council report in the browser so the human can review every result — PASS, UNCERTAIN, or FAIL. The human's review is how the system improves.

**PASS (keep)**:
1. Generate HTML report (above) + open in browser.
2. Write a markdown file to the Obsidian vault:
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
1. Generate HTML report (above) + open in browser. Even failures deserve review.
2. Log to `.omc/autoresearch/logs/failed/`.
3. Note it in results.tsv. Continue to next topic.

### Step 7: Log Results

Append one row to `.omc/autoresearch/results.tsv` (tab-separated):

```
timestamp	topic	axis	verdict	score	description
```

- timestamp: ISO format YYYY-MM-DD HH:MM
- topic: the research topic
- axis: which interest axis (neobio, ai_ml, business, tech_stack)
- verdict: PASS, UNCERTAIN, or FAIL
- score: total out of 100 (0 for crashes/skips)
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
9. **Update progress.md (CRITICAL — prevents context rot):**
   Append to `.omc/autoresearch/progress.md`:
   ```
   ## Exp#{N}: {topic}
   - Verdict: {PASS/UNCERTAIN/FAIL} ({score}/{max_score})
   - Learned: {one sentence — what did this experiment teach that wasn't obvious?}
   - Next time: {one sentence — what would you do differently?}
   - Follow-up: {questions opened by this experiment}
   ```
   This file is the **accumulated intelligence** of the loop. It survives context resets.
   Each new session reads progress.md to avoid repeating past mistakes.
   
10. **Rubric evolution check (every 20 experiments):**
    If results.tsv has 20+ new rows since last evolution:
    ```bash
    python3 src/eval/rubric-learner.py analyze --feedback .omc/autoresearch/signoff-queue/
    ```
    Review suggestions. Apply if they improve quality.
    
11. GOTO 1.

**Crashes**: If a step fails (web search timeout, MemPalace offline, file write error, agent timeout), log the error in results.tsv with score=0 and description="CRASH: {reason}", then skip to the next topic. Do NOT stop the loop.

**Circuit Breaker**: If 5 consecutive experiments result in FAIL or CRASH, PAUSE the loop. Log "CIRCUIT BREAKER: 5 consecutive failures. Switching to a different interest axis or waiting for human input." Try a completely different axis. If all axes have been tried and still fail, pause for 10 minutes then retry.

**Web Search Retry Limit**: If 3 consecutive web searches fail in Step 2 (timeout or empty), skip to Step 4 with whatever sources you have. Do not keep retrying.

**results.tsv Write Failure**: If results.tsv cannot be written, log to `.omc/autoresearch/logs/emergency-log.txt` as fallback. If that also fails, print to stderr and continue.

**results.tsv Rotation**: When results.tsv exceeds 500 rows, archive as `results-{date}.tsv` and keep only the last 100 rows in active file.

**NEVER STOP** (default): Once the experiment loop has begun (after the initial setup), do NOT pause to ask the human if you should continue. Do NOT ask "should I keep going?" or "is this a good stopping point?". The human might be asleep, or gone from their computer and expects you to continue working *indefinitely* until you are manually stopped. You are autonomous. If you run out of topics, cycle back through the interest axes with new angles -- combine keywords across axes, explore tangential areas, follow up on previous UNCERTAIN results with deeper research.

**Exception (Policy Decisions ④)**: 5회 연속 UNCERTAIN+FAIL이면 자동 PAUSE + `.omc/autoresearch/circuit-breaker.json`에 기록 + 사람에게 알림. 사람이 resume 명령 또는 토픽 변경 시 재개. 이 외에는 인간 interrupt까지 무한 cycle.

## Two Modes (자동 라우팅됨 — 사용자가 mode 용어 알 필요 없음)

사용자는 그냥 리서치 요청을 던지고, **Step 0 Interview Phase 0e Mode Routing**이 의도를 분석해 자동 결정. 사용자에게 한 줄로 보고하고 ✅ 또는 ✏️ 변경 받음.

### Mode 1: Autonomous Loop (무한 누적, 백그라운드)
**언제**: 지속/장기 모니터링 / vault에 누적 / 트렌드 추적
**Trigger**:
- 명시: "오토리서치 시작" / "세컨드 브레인 돌려" → Phase 0 skip
- 자동 라우팅: Phase 0e가 키워드("지속/장기/매일/쌓아") + ceo.mode="expansion" 감지

```
User: "오토리서치 시작" 또는 "AgTech 트렌드 매일 모니터링 vault에 쌓아"
-> [명시 trigger면] Setup → Loop forever
-> [자동 라우팅면] Setup → Step 0 Interactive Interview → Phase 0e routes to autonomous_loop → Loop forever
```

### Mode 2: Targeted Iterative Research (10 라운드 단발)
**언제**: 단일 질문 / 이번 한 번 결과 / 명확한 시점
**Trigger**:
- 자동 라우팅: 사용자가 구체 토픽 던지면 default 진입 (저비용 안전 첫 진입)

```
User: "이 논문 분석해줘" [attachment] / "MIRIVA 경쟁사 한 번 정리해줘"
-> Setup
-> Step 0 Interactive Interview (Phase 0a triage → 0b interview → 0c DesignDoc review → 0d ConsensusPlan review → 0e Mode Routing)
-> Phase 0e routes to targeted_iterative
-> Ingest document
-> 10-round improvement loop (iteration_hooks C20)
-> Retro summarize (C21) → learnings.jsonl 누적
-> Final report → STOP
```

In targeted mode, you run **MBB-style chapter-by-chapter** rounds (C24 — `src/council/round_layers.py`).

**각 round = 다른 chapter (10 layer 정의):**

| Round | Layer | Chapter | Focus |
|---|---|---|---|
| 1 | L1 | 시장 규모 + 컨텍스트 | TAM/SAM/SOM, 성장률, 트렌드 |
| 2 | L2 | 경쟁 지형 | 경쟁자 + 포지셔닝 매트릭스 |
| 3 | L3 | 고객 JTBD | functional/emotional/social JTBD |
| 4 | L4 | 재무 모델 | CAC/LTV/payback + 3-year P&L |
| 5 | L5 | 리스크 + 시나리오 | Top 5 risk + Best/Base/Worst |
| 6 | L6 | 실행 로드맵 | 0-3-6-12개월 마일스톤 |
| 7 | L7 | 거버넌스 + 운영 | RACI / KPI cadence / Build vs Buy |
| 8 | L8 | KPI 트리 | 북극성 + driver tree 5-7 |
| 9 | L9 | 반론 + 민감도 | 반론 3+ + 가정 ±20% sensitivity |
| 10 | L10 | Executive Synthesis | 권고 1줄 + So-What 3 + 90일 의사결정 |

**Type-aware 가중치 (Phase 0e research_type 반영):**
- `analytical` → L4(financial), L5(risk), L8(metrics) 우선
- `comparative` → L2(competitor), L3(JTBD), L9(sensitivities) 우선
- `predictive` → L6(roadmap), L7(governance) 우선
- `exploratory` → 균형 (L1→L10 순차)

**round 수가 < 10이면**: L1(foundation) + L10(synthesis)는 항상 포함, 나머지는 type 우선. 각 round prompt는 `select_layer_for_round(N, total_rounds, research_type)` + `layer_prompt_block(layer)`로 자동 주입됨.

**Iteration rules:**
- Default: 10 rounds (configurable via "N번 돌려" or "--rounds N")
- Each round reads previous round's gaps/recommendations from progress.md
- Each round does TARGETED web research on the specific gaps identified
- Council personas may change between rounds (fresh perspectives)
- eval-agent.py scores each round independently
- **Max score is dynamic** — read from rubric.json (`axes` count × `max` per axis). Do NOT hardcode /40.

**Git Ratchet (Karpathy autoresearch pattern):**
- Track `best_score` across rounds. Initialize to 0.
- After eval: if `this_score > best_score` → KEEP this round's output, update `best_score`
- If `this_score <= best_score` → DISCARD this round's output, keep previous best
- Quality is monotonically increasing — it can only go up, never down.

**Stop early if:**
- Score reaches 90%+ of max score (e.g., 36+ when max=40)
- 3 consecutive rounds DISCARDED (score not improving — plateau reached)

**Final output:** the BEST round's report (not the last round's). Ratchet ensures this.

**Progress tracking per round:**
```
## Round {N} of {target}
- Previous score: {N-1 score}/100
- Gaps addressed: {list from previous round's recommendations}
- New research: {what was searched to fill gaps}
- This score: {N score}/100
- Remaining gaps: {what's still weak}
```

After all rounds complete, generate the HTML report and open in browser.

## MBB Report Synthesis (C26 + C27 + C28)

Council 종료 시 `_finalize_council`이 자동으로 두 산출물을 생성:
- `council-report.json` — raw 토론 결과 (legacy)
- **`REPORT.md` — MBB-급 markdown deck** ⭐

`REPORT.md` 구조 (C26 `src/report/composer.py`):
1. Cover (topic + council_id + research_type + 메타 표)
2. Executive Summary (Net Position + Avg Confidence + Top Findings + 분포 표)
3. Table of Contents (chapter list)
4. Chapter 1~10 (round별, layer별 — C24 round_layers와 1:1 매핑)
5. Cross-Round Consensus & Dissent
6. Appendix A — Personas (expertise/bias/style)
7. Appendix B — Evidence Index (모든 출처 dedupe)

**C27 Visual Wire** (`src/report/visual_wire.py`):
- 각 chapter의 `framework_output`을 raw JSON 대신 시각화로 출력
- Porter 5 Forces → 5x3 markdown table (severity 이모지 🟢🟡🔴 포함)
- JTBD → 3x4 markdown table (functional/emotional/social × dimensions)
- SWOT → 2x2 quadrant table + TOWS
- North Star Tree / MECE Tree → mermaid graph
- Alias 폭넓게 지원 (severity/sev/level, north_star/star/metric, …)

**C28 Density Score** (`config/rubric.json` v2.2):
- 11 axis → **13 axis** (density + coverage_breadth 추가, 측정만 weight 0)
- `density`: 단락당 정량 수치·출처 인용 밀도 (0-10)
- `coverage_breadth`: 10 layer 중 충실 커버 비율 (0-10)
- 30 run 측정 후 weight 결정 (citation_fidelity 패턴 동일)

## Helper Scripts Reference

Scripts live in `src/{eval,hitl,ingest,runtime,council,search}/` (v0.4 재배치). Call via `Bash: python3 src/<dir>/{script}`:

| Script | Path | Purpose | When to use |
|--------|------|---------|-------------|
| `session-check.py` | `src/hitl/` | Check pending sign-offs, recent activity | Setup step 3 |
| `muchanipo-ingest.py <file> --wing X --room Y` | `src/ingest/` | Chunk + store document to MemPalace | Step 3 (document provided) |
| `eval-agent.py <report.json> --rubric rubric.json` | `src/eval/` | Score council output (v2.1 11-axis) | Step 5 |
| `citation_grounder.py <report.json>` | `src/eval/` | claim ↔ evidence 1:1 검증 패스 | Step 5 (PASS 게이트) |
| `rubric-learner.py analyze --feedback .omc/autoresearch/signoff-queue/` | `src/eval/` | 20+ signoff 후 rubric 진화 | After 20 feedbacks |
| `vault-router.py <eval.json> <report.json>` | `src/hitl/` | Route to vault/queue/discard | Step 6 |
| `signoff-queue.py list` / `approve <id>` | `src/hitl/` | List / approve queued items | On-demand |
| `signoff-report.py <id> --queue-dir ... --reports-dir ... --open` | `src/hitl/` | HTML report 생성 | All verdicts |
| `council-runner.py` | `src/council/` | Council deliberation engine | Step 4 |
| `insight-forge.py` / `react-report.py` | `src/search/` | 5W1H + RRF / ReACT report | Step 4 |
| `orchestrator.py` / `model-router.py` | `src/runtime/` | Loop coordination / model routing | Internal |

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
