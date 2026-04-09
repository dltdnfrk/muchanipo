---
name: arc-council
description: MiroFish 패턴 기반 다라운드 Council 토론 엔진. 동적 페르소나 + ReACT + emergent consensus.
trigger:
  - arc-council
  - council debate
  - 토론 시작
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
  - mcp__mempalace__mempalace_search
  - mcp__mempalace__mempalace_add_drawer
  - mcp__mempalace__mempalace_kg_add
  - mcp__mempalace__mempalace_kg_query
  - mcp__mempalace__mempalace_kg_timeline
  - mcp__mempalace__mempalace_diary_write
  - mcp__mempalace__mempalace_diary_read
---

# ARC Council — MiroFish-Pattern Multi-Round Debate Engine

A council deliberation system where dynamically generated personas debate on
a shared MemPalace knowledge graph until emergent consensus is reached.

**MiroFish Patterns Adopted:**
- `oasis_profile_generator.py`: Entity-to-persona conversion with individual/group distinction
- `zep_tools.py` InsightForge: LLM-based sub-query decomposition + semantic search + entity insights + relationship chains
- `report_agent.py` ReACT loop: Think-Act-Observe-Write with tool call parsing, observation injection, min/max enforcement
- Zep dependencies replaced with MemPalace MCP, search patterns (query decomposition, RRF) preserved

## Trigger Keywords
- "arc-council", "council debate", "토론 시작", "council 돌려"

## Architecture

```
[Input: topic + research brief]
         ↓
[Persona Generator → 3-7 personas]
  ├─ Ontology entities → generate_persona_from_entity() (MiroFish pattern)
  │   ├─ Individual entities: concrete person settings
  │   └─ Group entities: representative spokesperson settings
  ├─ Context enrichment via _build_entity_context() + MemPalace search
  └─ Fallback: static persona pool with role-based selection
         ↓
[Round 1: Independent Analysis — ALL PARALLEL]
  ├─ Persona 1 (via Claude): analyzes topic from their perspective
  ├─ Persona 2 (via Codex): analyzes from their perspective  
  ├─ Persona 3 (via OpenCode): analyzes from their perspective
  └─ ... up to 7 personas
         ↓
[Shared Memory: Record all positions to MemPalace KG]
         ↓
[Round 2-N: Cross-Evaluation + ReACT Debate]
  ├─ Each persona reads others' positions from MemPalace
  ├─ ReACT loop (MiroFish pattern):
  │   ├─ Tool call parsing: XML <tool_call> + bare JSON fallback
  │   ├─ Observation injection: REACT_OBSERVATION_TEMPLATE
  │   ├─ Min 3 tool calls enforced, max 5 per section
  │   └─ Conflict handling: tool_call + Final Answer in same response
  ├─ InsightForge search (MiroFish pattern):
  │   ├─ LLM-based sub-query generation (or 5W1H fallback)
  │   ├─ Multi-dimensional search via MemPalace
  │   ├─ RRF (Reciprocal Rank Fusion) integration
  │   ├─ Entity insight extraction
  │   └─ Relationship chain tracking
  ├─ Rebut, agree, or refine positions
  └─ Update MemPalace KG with new arguments
         ↓
[Consensus Check: convergence >= 0.7?]
  ├─ YES → Synthesize final output
  └─ NO + rounds < 5 → Continue debate
         ↓
[Final Synthesis + AAAK compressed log]
```

## Execution Protocol

### Phase 1: Setup

```python
# 1. Read topic and research brief
topic = read_input()
research = read_research_brief()  # from Researcher Agent

# 2. Generate personas
personas = Agent(subagent_type="persona-generator", prompt=topic + research)

# 3. Initialize council session
council_id = f"council-{timestamp}"
mkdir(".omc/autoresearch/council-logs/{council_id}/")
```

### Phase 2: Round 1 — Independent Analysis (PARALLEL)

Dispatch ALL personas simultaneously. Backend allocation depends on available tools:

```
# Phase 1: Claude-only (Codex/OpenCode added in Phase 2)
# All personas run as parallel Claude Agent subagents with different system prompts.
# This provides perspective diversity through PERSONA differences, not model differences.
#
# Phase 2 upgrade path (when Codex/OpenCode are configured):
# - Personas 1-2: Claude (via Agent subagent)
# - Personas 3-4: Codex (via ask_codex MCP tool)
# - Personas 5-7: OpenCode (via tools/opencode-council.sh)

# Current dispatch: all via Claude Agent tool
for each persona:
  Agent(
    subagent_type="general-purpose",
    prompt="{persona system prompt}\n{topic}\n{research brief}",
    model="sonnet",
    run_in_background=true
  )
```

Each persona receives:
```markdown
## Your Identity
Name: {persona.name}
Role: {persona.role}
Expertise: {persona.expertise}
Perspective: {persona.perspective_bias}
Style: {persona.argument_style}

## Topic
{topic}

## IMPORTANT: Do NOT rely on summaries. Search the source documents directly.
The original documents have been ingested into MemPalace.
You MUST use mempalace_search to find specific facts, numbers, and evidence.

## How to Search
- Use mempalace_search(query="keyword or question") to find relevant chunks
- Search for specific terms: "예산", "민감도", "CFU/mL", names, dates
- Each search returns original document chunks with exact text
- Cite the chunk source in your arguments: [Source: filename | Chunk: N]

## Your Task
1. Search MemPalace for information relevant to YOUR perspective
2. Analyze this topic from YOUR specific perspective using ORIGINAL DATA
3. State your position clearly (2-3 paragraphs) with specific citations
4. Identify key evidence supporting your position (cite chunk sources)
5. Note what you're uncertain about
6. Score your confidence (0.0-1.0)

## ReACT: Search and verify during analysis (MiroFish pattern)
You MUST use search tools during your analysis.

Available tools (adopted from MiroFish report_agent.py):
- insight_forge: Deep multi-dimensional search with sub-query decomposition + RRF
- mempalace_search: Search ingested documents for specific facts
- web_search: Verify claims against external sources

Tool call format (adopted from MiroFish report_agent.py:1067-1112):
<tool_call>
{"name": "insight_forge", "parameters": {"query": "search query"}}
</tool_call>

ReACT loop rules (adopted from MiroFish report_agent.py:1285-1500):
- Min 3 tool calls per section, max 5
- Each response: EITHER tool call OR "Final Answer:" (never both)
- Observation results injected as user messages
- Unused tool hints provided after each call
```

### Phase 3: Rounds 2-N — Cross-Evaluation + Debate

For each subsequent round:

```markdown
## Round {N} Instructions

You've seen all other personas' positions from Round {N-1}.

### Other Positions:
{Read from MemPalace KG or council log}

### Your Task:
1. For each other persona's position:
   - AGREE with specific points (cite which)
   - REBUT specific points (with evidence)
   - REFINE your own position based on new information
2. If any claim seems unverified → [SEARCH: query] to verify
3. State your UPDATED position
4. Score consensus with each other persona (0.0-1.0 per pair)
```

### Phase 4: Consensus Measurement

After each round, calculate convergence:

```
consensus_confidence = average of all pairwise agreement scores

where pairwise_agreement = (
  agreed_points / total_points_discussed
  + position_similarity_score  # 0-1 based on key claim overlap
) / 2
```

**Decision rules:**
- consensus >= 0.7 → STOP, synthesize
- consensus < 0.7 AND round < 5 → continue
- round == 5 AND consensus < 0.5 → escalate to human
- round == 5 AND consensus 0.5-0.7 → synthesize with dissent noted

### Phase 5: Synthesis

Generate the final council output:

```markdown
# Council Report: {topic}

## Metadata
- Council ID: {council_id}
- Date: {date}
- Personas: {list}
- Rounds: {N}
- Consensus: {confidence}
- Duration: {minutes}

## Consensus Position
{The synthesized agreement — what all/most personas converged on}

## Key Arguments
{The strongest arguments that shaped the consensus}

## Dissenting Views
{Any unresolved disagreements, with persona attribution}

## Evidence Gathered (ReACT)
{All searches/verifications performed during debate}

## Recommendations
{Actionable recommendations from the consensus}

## Open Questions
{Questions that emerged but weren't resolved}
```

### Phase 6: Logging

1. Save full council log to `.omc/autoresearch/council-logs/{council_id}/`
2. Compress debate log with AAAK format for MemPalace storage
3. Store key facts as MemPalace KG temporal triples
4. Pass council report to Eval Agent

## AAAK Compression Format for Council Logs

```
COUNCIL:{council_id}|T:{topic}|R:{rounds}|C:{confidence}
P1:{name}({role})|POS:{position_summary}|CONF:{confidence}
P2:{name}({role})|POS:{position_summary}|CONF:{confidence}
...
AGREE:{points of agreement}
DISSENT:{points of disagreement}
REACT:[{search_query}→{result}]
VERDICT:{final_consensus}
```

## Fallback Strategy

| Situation | Action |
|-----------|--------|
| Codex unavailable | Redistribute personas to Claude + OpenCode |
| OpenCode unavailable | Redistribute to Claude + Codex |
| Both unavailable | Claude-only with critic agent as devil's advocate |
| Persona deadlock (no convergence by R5) | Synthesize majority + flag for human review |
| ReACT search fails | Continue with available evidence, note gaps |

## Integration Points

- **Input from**: Researcher Agent (research brief) or direct user input
- **Persona source**: persona-generator agent
- **Shared memory**: MemPalace KG (temporal triples)
- **Output to**: arc-evaluator agent
- **Logs**: .omc/autoresearch/council-logs/
