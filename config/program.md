# AutoResearch Program — Hyunjun's Second Brain

## Identity
- Owner: Hyunjun (NeoBio CEO, AI/AgTech entrepreneur)
- Purpose: Continuously expand personal ontology through autonomous research and council deliberation
- Output: Obsidian vault (`MUCHANIPO_VAULT_PATH`, default `~/Documents/Hyunjun/`) knowledge wiki + decision reports

## Interest Axes

### 1. NeoBio & AgTech
- Keywords: 과수 진단, 형광 프로브, 정밀농업, MIRIVA, 식물 병해충, 스마트팜
- Depth: deep
- Update frequency: daily
- Focus: 경쟁사 동향, 시장 규모, 규제 변화, 기술 트렌드

### 2. AI/ML & Agent Systems
- Keywords: LLM agent, multi-agent, prompt engineering, RAG, MCP, tool use, agentic workflow
- Depth: deep
- Update frequency: daily
- Focus: 새로운 아키텍처 패턴, 오픈소스 프로젝트, 벤치마크, 실용 적용

### 3. Business & Strategy
- Keywords: SaaS pricing, go-to-market, B2B 농업, 스타트업, 투자, PMF
- Depth: moderate
- Update frequency: weekly
- Focus: pricing 전략, GTM 사례, 농업 B2B 성공/실패 사례

### 4. Technology Stack
- Keywords: React Native, Expo, BLE, edge AI, Supabase, TypeScript
- Depth: moderate
- Update frequency: weekly
- Focus: 버전 업데이트, breaking changes, 성능 최적화, 보안 패치

## Exploration Rules

### Topic Selection
- Rotate through interest axes proportionally to depth setting (deep=3x, moderate=1x)
- Prioritize topics with high "novelty score" (not already in vault)
- Cross-reference: prefer topics that connect 2+ interest axes
- Follow-up: if previous research opened new questions, pursue them first

### Research Depth
- Light scan: 3-5 sources, single-model analysis (for weekly/low-priority)
- Deep dive: 8-12 sources, full council deliberation (for daily/high-priority)
- Follow-up: targeted search on specific claims or contradictions

### Quality Gates
- Minimum 2 credible sources per factual claim
- No speculative information stored as fact
- Contradictions with existing vault knowledge trigger mandatory council debate
- Cross-industry benchmarking: don't limit user flow analysis to AgTech only

## Eval Rubric (v1 — Initial)

### Scoring Axes (0-10 each, 10 axes, total 100)
1. **Usefulness**: Does this knowledge help Hyunjun make better decisions or build better products?
2. **Reliability**: Are claims well-sourced? Would they hold up under scrutiny?
3. **Novelty**: Is this genuinely new information not already in the vault?
4. **Actionability**: Can this be acted upon? Does it suggest concrete next steps?
5. **Completeness**: Does the analysis cover all key aspects without blind spots?
6. **Evidence Quality**: Are cited sources credible and diverse?
7. **Perspective Diversity**: Are multiple stakeholder viewpoints represented?
8. **Coherence**: Are consensus and recommendations logically consistent?
9. **Depth**: Does the analysis dig into root causes, not just surface observations?
10. **Impact**: Would implementing the recommendations create real change?

### Thresholds
- PASS: total >= 70 (out of 100)
- UNCERTAIN: total 50-69 → queue for human sign-off
- FAIL: total < 50 → discard, log reason

### Rubric Evolution
- Track human sign-off decisions (approve/reject/modify)
- After 20+ sign-offs, analyze patterns:
  - What did human approve that scored UNCERTAIN? → lower threshold for that pattern
  - What did human reject that scored PASS? → add new scoring axis or adjust weights
- Store rubric version history in .omc/autoresearch/rubric-history/

## Obsidian Vault Structure

### Target Wings (MemPalace mapping)
- wing_neobio → `${MUCHANIPO_VAULT_PATH}/Neobio/`
- wing_tech → `${MUCHANIPO_VAULT_PATH}/Idea Note/`
- wing_business → `${MUCHANIPO_VAULT_PATH}/Neobio/funding/` + `memo/`
- wing_research → `${MUCHANIPO_VAULT_PATH}/Feed/` (new research outputs)

### File Naming
- Format: `YYYY-MM-DD-{topic-slug}.md`
- Tags: #autoresearch, #council, #{interest-axis}
- Frontmatter: source, date, confidence, personas, council-id

### Linking Rules
- Always search vault for existing related notes before creating new ones
- Use [[wikilinks]] to connect to existing knowledge
- Create MOC (Map of Content) files per interest axis, updated weekly

## Council Configuration

### Participants
- Claude Code (claude-opus-4-6): Critical analyst — challenges assumptions, seeks counterexamples
- Codex CLI (gpt-5.3-codex): Pragmatic engineer — focuses on feasibility, cost, implementation
- OpenCode (Hephaestus): Academic researcher — cites papers, data-driven, long-term trends

### Debate Rules
- Max rounds: 5 (auto-terminate if no convergence by round 5)
- Convergence threshold: 0.7 consensus confidence
- ReACT enabled: agents can search web, verify claims during debate
- Shared memory: MemPalace KG (temporal triples)

### Persona Generation
- Dynamically generated from input document analysis
- Each persona gets: name, role, expertise, perspective bias, argument style
- Minimum 3, maximum 7 personas per session
- Personas persist in MemPalace Agent Diary (AAAK compressed) for expertise accumulation

## Prohibited
- Storing speculative information as fact
- Claims without source attribution
- Modifying existing vault notes without clear justification
- Exceeding 5 council rounds per topic (escalate to human instead)
- Ignoring contradictions with existing knowledge

## Loop Control
- NEVER STOP. Once the research loop begins, continue indefinitely.
- Between topics: 30-second cooldown for state persistence
- On error: log error, skip to next topic, retry failed topic in next cycle
- On human sign-off request: pause current topic, queue it, continue with next
