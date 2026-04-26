# C30 Redesign — Idea-to-Council Pipeline Architecture

**작성:** 2026-04-26
**상태:** 확정 방향 — PR #20 Model Router 중심 설계를 대체/supersede
**배경:** PR #20 (`design(c30): Model Router multi-agent design proposals + 합성 doc`)은 `src/router/` 중심으로 비용/프로바이더/config를 나누는 설계였다. 사용자 피드백에 따라 muchanipo의 핵심 경계는 모델 라우팅이 아니라 **자율과학루프의 사용자 생명주기**로 재정의한다.

---

## 0. 핵심 결정

> muchanipo는 "모델을 잘 고르는 시스템"이 아니다.
>
> muchanipo는 **아이디어 덤프를 연구 가능한 PRD-style brief로 정제하고, 오토리서치와 보고서를 거쳐, 보고서 기반 토론 에이전트(mirofish 포함)를 만들고, council에서 심의/합의하는 시스템**이다.

따라서 C30 구현은 `src/router/` top-level package를 만들지 않는다.

- Model Router는 top-level architecture boundary가 아니다.
- 모델/툴/워커 실행은 `src/execution/`의 하위 gateway로 둔다.
- 비용/안전/audit/profile/config/health는 router 내부가 아니라 `src/governance/`가 맡는다.
- 최상위 흐름은 `Idea → Brief → Research → Report → Agents → Council` 이다.

---

## 1. 최종 사용자 흐름

```text
1. Idea Dump
   사용자가 생각나는 대로 아이디어/질문/문제의식을 던진다.

2. PRD-style Interview
   대화형 질문으로 연구 목적, 범위, 산출물, 품질 기준을 구체화한다.
   결과물은 ResearchBrief.

3. AutoResearch
   ResearchBrief를 바탕으로 자료 수집, evidence capture, finding synthesis를 수행한다.

4. Report Generation
   오토리서치 결과를 출처/한계/신뢰도 포함 ResearchReport로 생성한다.

5. Debate Agent Generation
   ResearchReport를 기반으로 관점별 토론 에이전트를 생성한다.
   mirofish는 보고서의 약한 전제/빈틈/반례를 집요하게 찾는 critic 계열 agent다.

6. Council
   생성된 에이전트들이 보고서를 비판/확장/합의/반박한다.
   최종 결론, unresolved disagreements, next actions를 산출한다.
```

한 줄 요약:

```text
Idea → Brief → Research → Report → Agents → Council → Decision / Next Action
```

---

## 2. Top-level module boundary

```text
src/
  pipeline/      # 전체 idea-to-council orchestration/state/stages
  intake/        # raw idea dump capture/normalization
  interview/     # PRD-style interview, coverage rubric, ResearchBrief 생성
  research/      # AutoResearch planner/runner/query/synthesis
  evidence/      # evidence store, citation, provenance, source quality
  report/        # ResearchReport schema/composer/templates
  agents/        # report 기반 DebateAgentSpec 생성, mirofish 포함
  council/       # council session/moderator/round/consensus
  knowledge/     # learnings, claims, dream-cycle, vault sync
  execution/     # model/tool/worker runtime, provider adapters
  governance/    # budget, safety, audit, profile, config, health
  eval/          # 기존 rubric/critic/signoff/plateau 유지
```

### 왜 `src/router/`가 아닌가?

모델 호출은 모든 단계에서 사용되는 실행 수단이다.

- interview 질문 생성에도 모델 사용
- autoresearch synthesis에도 모델 사용
- report composer에도 모델 사용
- debate agent generation에도 모델 사용
- council round에도 모델 사용

따라서 모델 라우팅은 제품 경계가 아니라 `execution.models`의 하위 기능이어야 한다.

---

## 3. Core data contracts

### 3.1 IdeaDump

```python
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class IdeaDump:
    raw_text: str
    source: str = "user"
    created_at: datetime | None = None
    attachments: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
```

역할:
- 사용자의 자유 입력을 보존한다.
- 너무 일찍 구조화하지 않는다.
- 이후 interview에서 원문을 계속 참조할 수 있게 한다.

### 3.2 ResearchBrief

```python
@dataclass
class ResearchBrief:
    raw_idea: str
    research_question: str
    purpose: str
    context: str
    known_facts: list[str]
    deliverable_type: str
    quality_bar: str
    constraints: list[str]
    success_criteria: list[str]
    coverage_score: float
```

역할:
- PRD-style interview의 최종 산출물.
- AutoResearch가 바로 실행할 수 있는 최소 계약.
- C21/C22의 interview/rubric 결과를 여기에 정규화한다.

### 3.3 ResearchPlan

```python
@dataclass
class ResearchPlan:
    brief_id: str
    queries: list[str]
    evidence_targets: list[str]
    expected_deliverables: list[str]
    stop_conditions: list[str]
    risk_notes: list[str]
```

역할:
- ResearchBrief를 실행 가능한 검색/수집/합성 계획으로 바꾼다.
- `research.runner`가 이 plan을 실행한다.

### 3.4 EvidenceRef / Finding

```python
@dataclass
class EvidenceRef:
    id: str
    source_url: str | None
    source_title: str | None
    quote: str | None
    source_grade: str  # A/B/C/D
    provenance: dict

@dataclass
class Finding:
    claim: str
    support: list[EvidenceRef]
    confidence: float
    limitations: list[str]
```

역할:
- report와 council이 근거를 잃지 않게 한다.
- citation laundering 방지.

### 3.5 ResearchReport

```python
@dataclass
class ResearchReport:
    brief_id: str
    title: str
    executive_summary: str
    findings: list[Finding]
    evidence_refs: list[EvidenceRef]
    open_questions: list[str]
    confidence: float
    limitations: list[str]
```

역할:
- AutoResearch 결과의 canonical artifact.
- 이후 debate agent 생성의 입력.

### 3.6 DebateAgentSpec

```python
@dataclass
class DebateAgentSpec:
    name: str
    role: str
    perspective: str
    expertise: list[str]
    challenge_targets: list[str]
    source_report_id: str
    system_prompt: str
```

역할:
- report 기반 토론 에이전트를 선언적으로 생성한다.
- mirofish, domain expert, skeptic, builder, evidence auditor 등을 포함할 수 있다.

### 3.7 CouncilSession

```python
@dataclass
class CouncilSession:
    report_id: str
    agents: list[DebateAgentSpec]
    rounds: list[dict]
    consensus: str | None
    disagreements: list[str]
    next_actions: list[str]
```

역할:
- 보고서 기반 심의의 실행 기록.
- 최종 conclusion뿐 아니라 unresolved disagreements와 다음 실험/개발 과제를 남긴다.

---

## 4. Module responsibilities

### 4.1 `src/pipeline/`

```text
src/pipeline/
  __init__.py
  stages.py              # Stage enum: IDEA_DUMP, INTERVIEW, RESEARCH, REPORT, AGENTS, COUNCIL
  state.py               # PipelineState, RunStatus
  idea_to_council.py     # 전체 orchestration
```

책임:
- 전체 flow의 상태 전이.
- 각 stage의 input/output artifact id 연결.
- resume/retry/stop policy는 여기서 호출하되 구현은 governance/eval에 위임.

### 4.2 `src/intake/`

```text
src/intake/
  __init__.py
  idea_dump.py           # IdeaDump dataclass
  normalizer.py          # raw text cleanup, attachment metadata
```

책임:
- raw idea 보존.
- 너무 이른 판단/요약 금지.
- interview에 넘길 최소 정규화.

### 4.3 `src/interview/`

```text
src/interview/
  __init__.py
  prompts.py             # PRD-style questions
  rubric.py              # coverage/quality gate
  session.py             # interview state, next question selection
  brief.py               # ResearchBrief creation
```

책임:
- 기존 C21/C22 `src/intent/*` 기능의 목적지.
- startup/founder tone이 아니라 research PRD tone 유지.
- 충분히 명확해지면 조기 종료.

### 4.4 `src/research/`

```text
src/research/
  __init__.py
  planner.py             # ResearchBrief → ResearchPlan
  runner.py              # plan 실행
  queries.py             # search query generation
  synthesis.py           # Finding synthesis
```

책임:
- AutoResearch의 실행 계획과 synthesis.
- evidence store와 report composer 사이의 연결.

### 4.5 `src/evidence/`

```text
src/evidence/
  __init__.py
  artifact.py
  store.py
  citation.py
  provenance.py
  quality.py
```

책임:
- source, quote, provenance, quality grade.
- citation grounding과 fabricated quote 방지.

### 4.6 `src/report/`

```text
src/report/
  __init__.py
  schema.py              # ResearchReport, Finding, EvidenceRef re-export 가능
  composer.py            # findings → markdown/json report
  templates/
    research_report.md
```

책임:
- evidence-backed report 생성.
- executive summary, findings, open questions, limitations 포함.

### 4.7 `src/agents/`

```text
src/agents/
  __init__.py
  generator.py           # ResearchReport → DebateAgentSpec[]
  mirofish.py            # mirofish critic profile
  personas.py            # expert/skeptic/builder/evidence auditor
  prompts.py
```

책임:
- 보고서 내용을 기반으로 토론 에이전트 생성.
- agent가 raw topic이 아니라 report를 읽고 토론하게 만든다.

### 4.8 `src/council/`

```text
src/council/
  __init__.py
  session.py
  round.py
  moderator.py
  consensus.py
  outputs.py
```

책임:
- DebateAgentSpec 기반 council 실행.
- round별 주장/반박/합의/불일치 기록.
- next action 생성.

### 4.9 `src/execution/`

```text
src/execution/
  __init__.py
  runtime.py             # ExecutionRuntime
  task.py                # TaskSpec, TaskResult
  workers.py             # worker/lane dispatch
  tools.py               # ToolRegistry
  models.py              # ModelGateway (former router role)
  providers/
    __init__.py
    base.py
    mock.py
    anthropic.py
    openai.py
    ollama.py
    codex_cli.py
```

책임:
- 모델/툴/워커 실행.
- fallback/retry/timeout.
- top-level architecture가 아니라 supporting runtime.

### 4.10 `src/governance/`

```text
src/governance/
  __init__.py
  budget.py              # RunBudget, reserve/reconcile/log
  safety.py              # safety policy adapter
  audit.py               # AuditLog
  profiles.py            # dev/staging/prod profile
  config.py              # config loader
  health.py              # provider/tool health
```

책임:
- 비용, 안전, audit, profile, health.
- router에 종속되지 않는다.
- 전체 pipeline에 횡단 적용.

---

## 5. Existing code migration notes

### 5.1 `src/intent/*`

기존 C21/C22 산출물은 삭제하지 말고 목적지별로 이동/alias한다.

```text
src/intent/interview_prompts.py  → src/interview/prompts.py
src/intent/interview_rubric.py   → src/interview/rubric.py
src/intent/office_hours.py       → src/interview/session.py 또는 src/interview/brief.py
src/intent/plan_review.py        → src/research/planner.py 또는 src/interview/brief.py
src/intent/retro.py              → src/knowledge/retro.py
src/intent/learnings_log.py      → src/knowledge/learnings.py
```

초기 구현에서는 compatibility import를 허용한다.

### 5.2 `src/runtime/model-router.py`

기존 1200 LOC monolith는 바로 삭제하지 않는다.

```text
src/runtime/model-router.py
  → deprecated compatibility layer
  → internally delegate to src/execution/models.py when ready
```

원칙:
- 신규 코드는 `src/execution/models.py` 사용.
- 기존 path는 `DeprecationWarning`만 남긴다.
- 완전 삭제는 migration test가 green인 다음 sprint에서 수행.

### 5.3 PR #20 design docs

`_assignments/ASSIGNMENT_C30_router_decided.md`는 historical artifact로 유지하되 superseded note를 추가한다.

---

## 6. Revised implementation lanes

C30-impl은 보류한다. 다음 구현은 C31로 분리한다.

### Lane A — Pipeline + Intake + Interview

목표:
> idea dump → ResearchBrief 생성까지 end-to-end skeleton.

파일:
```text
src/pipeline/stages.py
src/pipeline/state.py
src/pipeline/idea_to_council.py
src/intake/idea_dump.py
src/intake/normalizer.py
src/interview/brief.py
src/interview/session.py
tests/test_idea_to_brief.py
```

Acceptance:
- raw idea를 넣으면 ResearchBrief skeleton이 생성된다.
- coverage score가 threshold 미만이면 추가 질문이 필요하다고 표시한다.
- 기존 `src/intent`와 충돌하지 않는다.

### Lane B — AutoResearch + Evidence

목표:
> ResearchBrief → ResearchPlan → evidence-backed Finding skeleton.

파일:
```text
src/research/planner.py
src/research/runner.py
src/research/queries.py
src/research/synthesis.py
src/evidence/artifact.py
src/evidence/store.py
src/evidence/provenance.py
src/evidence/quality.py
tests/test_research_runner.py
tests/test_evidence_store.py
```

Acceptance:
- ResearchBrief에서 query list를 만든다.
- EvidenceRef는 source_grade와 provenance를 필수로 가진다.
- API key 없이 mock evidence로 테스트 가능하다.

### Lane C — Report + Debate Agent Generation

목표:
> Findings → ResearchReport → DebateAgentSpec[] 생성.

파일:
```text
src/report/schema.py
src/report/composer.py
src/report/templates/research_report.md
src/agents/generator.py
src/agents/mirofish.py
src/agents/personas.py
src/agents/prompts.py
tests/test_report_composer.py
tests/test_agent_generator.py
```

Acceptance:
- ResearchReport markdown가 findings/evidence/limitations/open_questions를 포함한다.
- agent generator는 최소 mirofish + evidence auditor + builder + domain expert를 생성한다.
- 각 DebateAgentSpec은 source_report_id를 보존한다.

### Lane D — Council + Execution/Governance

목표:
> DebateAgentSpec들을 council session에서 실행하고 budget/safety/audit를 횡단 적용.

파일:
```text
src/council/session.py
src/council/round.py
src/council/moderator.py
src/council/consensus.py
src/council/outputs.py
src/execution/runtime.py
src/execution/models.py
src/execution/providers/mock.py
src/governance/budget.py
src/governance/audit.py
src/governance/profiles.py
tests/test_council_session.py
tests/test_budget.py
```

Acceptance:
- mock provider만으로 council 1 round가 실행된다.
- budget ledger는 reserve/reconcile/log 흐름을 가진다.
- audit log는 stage, agent, model/provider, cost estimate를 기록한다.

---

## 7. Configuration decisions revised

PR #20의 사용자 결정 4개는 다음처럼 재해석한다.

### 7.1 Profile default

기존:
```text
router profile default = dev
```

수정:
```text
science-loop run profile default = dev
```

Resolution:
```text
--profile > MUCHANIPO_PROFILE > dev
```

Profile은 model뿐 아니라 budget, safety strictness, evidence strictness, loop aggressiveness에 적용된다.

### 7.2 Local model priority

기존:
```text
local 1순위 = Qwen3-30B-A3B
```

수정:
```text
stage별 execution model policy
```

예:
```text
INTERVIEW           → sonnet-class or mock in tests
RESEARCH_SYNTHESIS  → sonnet/deepseek fallback
REPORT_COMPOSER     → high-quality remote first
AGENT_GENERATION    → sonnet-class
COUNCIL_ROUND       → stage-specific mix
DREAM_CYCLE         → local qwen first
```

Qwen3는 전역 hard default가 아니라 local-preferred stage에서 primary로 둔다.

### 7.3 Session budget

기존:
```text
router session budget = dev $5 / prod $50
```

수정:
```text
pipeline run budget = dev $5 / prod $50
```

Budget은 모델 호출뿐 아니라 retries/fallbacks/tool calls/worker execution을 포함한다.

### 7.4 model-router.py 처리

기존:
```text
deprecate → 다음 sprint 삭제
```

수정:
```text
deprecate compatibility layer → src/execution/models.py로 점진 흡수
```

삭제 시점은 migration coverage가 충분할 때로 미룬다.

---

## 8. Definition of Done for C30-redesign

- [x] PR #20 router-centered design을 historical artifact로 유지
- [x] Idea-to-Council Pipeline architecture 문서화
- [x] top-level module boundary 재정의
- [x] Model Router를 `src/execution/models.py` 하위 gateway로 격하
- [x] governance plane을 budget/safety/audit/profile/config/health로 분리
- [x] C31 4-lane implementation plan 정의
- [ ] C31 implementation PR 시작

---

## 9. Short directive for future workers

```text
Do not implement top-level src/router for C30.
Implement muchanipo around the Idea-to-Council lifecycle:
IdeaDump → ResearchBrief → AutoResearch → ResearchReport → DebateAgentSpec(mirofish) → CouncilSession.

Model routing belongs under src/execution/models.py.
Budget/config/health/safety/audit belong under src/governance/.
Use mock providers first so tests run without API keys.
```
