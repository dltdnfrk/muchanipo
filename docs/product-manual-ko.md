# Muchanipo 제품 설명서

> Autonomous Second Brain Engine — 아이디어를 입력하면 인터뷰, 목표 설정, 자료 수집, 근거 검증, Council 토론, 보고서 작성, 지식 축적까지 이어지는 로컬 우선 자율 리서치 엔진.

## 1. 제품 개요

Muchanipo는 사용자의 연구 주제나 제품 아이디어를 구조화된 리서치 산출물로 바꾸는 CLI/TUI/데스크톱 기반 리서치 시스템입니다. 핵심 제품은 Python CLI/TUI 런너이며, Tauri 데스크톱 앱은 같은 파이프라인 이벤트 스트림을 보는 viewer/control shell 역할을 합니다.

제품의 기본 철학은 다음과 같습니다.

- **원자료와 정리된 지식의 분리**: 사람이 넣은 원문은 `raw/`에 보존하고, LLM이 정리한 지식은 `wiki/`에 축적합니다.
- **근거 중심 리서치**: 보고서는 생성 텍스트만 믿지 않고 evidence, citation, provenance, DOI/출처 구조를 함께 기록합니다.
- **다중 관점 Council**: 여러 persona/agent 관점에서 토론하고, 합의·반론·리스크를 보고서에 반영합니다.
- **Human-in-the-Loop**: 불확실하거나 영향이 큰 판단은 Plannotator/HITL 게이트를 통해 사람이 승인·수정할 수 있게 합니다.
- **Offline-first capable**: `demo`, `--offline`, `MUCHANIPO_OFFLINE=1` 경로는 외부 서버와 통신하지 않고 deterministic mock provider로 동작합니다.

주요 근거 파일:

- `README.md`
- `src/muchanipo/server.py`
- `src/pipeline/stages.py`
- `src/pipeline/runner.py`
- `app/muchanipo-tauri/README.md`
- `docs/data-transmission-notice.md`

## 2. 대상 사용자와 사용 시나리오

Muchanipo는 다음 상황에 적합합니다.

| 사용자 | 대표 사용 시나리오 |
| --- | --- |
| 창업자 / 제품 기획자 | 한 문장 아이디어를 시장성, 경쟁, JTBD, 리스크, 실행 로드맵이 포함된 보고서로 확장 |
| 연구자 / 분석가 | 주제별 학술 검색, 근거 수집, Council 토론, 보고서 초안 생성 |
| 컨설턴트 / 전략 담당자 | MBB식 6장 보고서 구조와 Pyramid/SCR 기반 결론 정리 |
| 로컬 AI 워크플로우 운영자 | Claude/Gemini/Kimi/Codex/OpenCode CLI를 단계별 provider로 라우팅 |
| 개인정보/민감 주제 사용자 | 외부 전송 없는 deterministic offline mode로 안전한 데모·검토 수행 |

예시 주제:

```bash
muchanipo run "딸기 농가용 저비용 분자진단 키트 시장성" --offline
muchanipo tui "딸기 진단키트 시장성" --online
muchanipo run "AI 기반 B2B 영업 자동화 시장 진입 전략" --depth deep
```

## 3. 제품 구성요소

### 3.1 Python CLI/TUI 런타임

CLI/TUI는 제품의 중심 실행 환경입니다. `pyproject.toml`의 console script는 `muchanipo = "src.muchanipo.server:main"`로 연결되어 있고, `src/muchanipo/server.py`가 주요 command를 정의합니다.

주요 명령:

| 명령 | 목적 |
| --- | --- |
| `muchanipo demo` | provider credential 없이 deterministic offline sample run 실행 |
| `muchanipo run "주제" --offline` | 터미널에서 전체 파이프라인 실행 |
| `muchanipo tui "주제"` | 터미널 대시보드 형태로 실행 |
| `muchanipo doctor` | 로컬 런타임 readiness 점검 |
| `muchanipo status` | provider CLI/API 상태 확인 |
| `muchanipo runs` | 최근 run summary 조회 |
| `muchanipo contracts` | stable JSON contract 확인 |
| `muchanipo references` | 외부 reference project runtime readiness 확인 |
| `muchanipo orchestrate` | tmux/smux operator-worker 상태 확인 및 안전 cleanup |

JSON inspection 명령은 `--json`을 지원하며, agent/script가 안정적으로 읽을 수 있도록 `schema_version`, `command` 같은 top-level key를 유지합니다. 상세 contract는 `docs/cli-json-contracts.md`에 있습니다.

### 3.2 Tauri 데스크톱 앱

Tauri 앱은 `app/muchanipo-tauri/`에 있으며, Python CLI/TUI runner 위에서 동작하는 데스크톱 viewer/control shell입니다.

스택:

- Tauri 2 + Rust shell
- Vite + React 18 + TypeScript frontend
- `python3 -m muchanipo serve` subprocess bridge
- 같은 pipeline core를 CLI/TUI/Tauri가 공유

주요 화면:

| Route | React Page | 설명 |
| --- | --- | --- |
| `/` | `IdeaSubmit.tsx` | 연구 주제/아이디어 입력 |
| `/run/:runId` | `RunProgress.tsx` | 실행 단계, provider/runtime 상태, evidence 진행 확인 |
| `/report/:runId` | `ReportView.tsx` | 최종 보고서 확인 |
| `/settings` | `Settings.tsx` | 실행 설정 및 환경 확인 |

Rust side command는 `app/muchanipo-tauri/src-tauri/src/main.rs`에서 등록합니다.

- `start_pipeline`
- `send_action`
- `check_cli_status`
- `check_cli_smoke`
- `open_cli_auth`
- `get_buffered_events`
- `pipeline_runtime_status`

이 명령들은 `python_bridge.rs`를 통해 Python runtime과 연결됩니다.

## 4. 전체 파이프라인

Muchanipo의 canonical lifecycle은 `src/pipeline/stages.py`에 정의되어 있습니다.

```text
idea_dump → interview → targeting → research → evidence → council → report → vault → agents → done
```

CLI full pipeline에서는 `src/muchanipo/server.py` 기준으로 다음 stage 이름을 사용합니다.

```text
intake → interview → targeting → research → evidence → council → report → finalize
```

두 이름 체계는 `src/pipeline/runner.py`의 `STAGE_MAP`에서 연결됩니다.

### 4.1 Intake / Idea Dump

사용자의 원문 아이디어를 캡처하고 시스템 내부에서 다룰 수 있는 structured idea로 정규화합니다. 이 단계는 이후 interview, research brief, targeting map의 출발점입니다.

관련 코드:

- `src/intake/normalizer.py`
- `src/pipeline/idea_to_council.py`

### 4.2 Interview / 요구사항 정리

아이디어가 모호할 때 필요한 질문을 생성하고, 제품 요구사항·MVP 범위·데이터 모델·phase·stack/auth 선택 같은 항목을 정리합니다. Reference 문서에 따르면 GPTaku `show-me-the-prd` 패턴을 vendored source와 local adapter로 연결합니다.

산출물 예:

- `PRD/01_PRD.md`
- `PRD/02_DATA_MODEL.md`
- `PRD/03_PHASES.md`
- `PRD/04_PROJECT_SPEC.md`

관련 파일:

- `src/interview/show_me_the_prd_port.py`
- `docs/reference-projects.md`
- `docs/reference-implementation-inventory.md`

### 4.3 Targeting / 연구 지도 작성

연구 질문, 목표 기관/저널/논문, 우선순위, 소스 전략을 정합니다. live academic targeting이 켜진 경우 OpenAlex seed papers에서 여섯 가지 academic sync adapter로 fallback할 수 있습니다.

관련 파일:

- `src/targeting/builder.py`
- `src/research/academic/`
- `docs/reference-implementation-inventory.md`

### 4.4 Research / 자료 수집

자료 수집 단계는 Karpathy Autoresearch, InsightForge, MemPalace, academic API 계층을 참고합니다. Offline mode에서는 mock/fixed data로 deterministic하게 동작하고, source research/live mode에서는 실제 search/adapter/provider 경로를 사용할 수 있습니다.

핵심 개념:

- 검색 질문 분해
- source-backed evidence 수집
- 반복형 autoresearch keep/discard loop
- local memory-first retrieval
- academic API 기반 논문/DOI/초록/인용 정보 수집

관련 파일:

- `src/research/karpathy_autoresearch.py`
- `src/research/mempalace.py`
- `src/search/insight-forge.py`
- `src/research/runner.py`
- `src/research/academic/`

### 4.5 Evidence / 근거 검증

수집된 정보를 보고서에 넣기 전에 evidence ref, source locator, DOI metadata, quote grounding, provenance를 확인합니다. `docs/reference-implementation-inventory.md`는 Stage 4 evidence grounding이 optional integration을 믿기 전에 기본 source structure를 fail-closed로 검증한다고 설명합니다.

관련 파일:

- `src/evidence/`
- `src/evidence/store.py`
- `src/evidence/findings.py`
- `src/evidence/artifact.py`

### 4.6 Council / 다중 관점 토론

Council 단계는 여러 persona/agent를 구성하고 라운드별 토론을 실행합니다. 목표는 단일 LLM 답변보다 더 다양한 관점, 반론, 리스크, 실행 판단을 얻는 것입니다.

참고/통합 패턴:

- MiroFish: graph/world/profile/deep interaction 기반 local runtime adaptation
- OASIS/CAMEL: private analysis → blinded peer review → chairman synthesis protocol
- Nemotron-Personas-Korea: 한국 맥락 persona seed
- HACHIMI: persona propose/validate/revise/deduplicate 패턴
- MAP-Elites: risk appetite / innovation orientation 기반 다양성 유지

관련 파일:

- `src/council/`
- `src/council/session.py`
- `src/council/persona_generator.py`
- `src/council/persona_sampler.py`
- `src/council/oasis_camel_runtime.py`
- `src/agents/mirofish.py`

### 4.7 Report / 보고서 생성

Council round 결과와 evidence를 MBB식 6장 구조, Pyramid/SCR 방식으로 정리합니다. Offline demo fixture도 10개의 round digest를 사용해 같은 보고서 artifact 경로를 생성합니다.

대표 artifact:

- `REPORT.md`
- `events.jsonl`
- `summary.json`

기본 저장 위치:

```text
~/.local/share/muchanipo/runs/<run-id>/
```

관련 파일:

- `src/report/chapter_mapper.py`
- `src/report/pyramid_formatter.py`
- `src/report/schema.py`
- `src/muchanipo/server.py`

### 4.8 Vault / 지식 축적

최종 결과는 raw/wiki/GBrain 스타일의 구조를 따라 지식 저장소에 축적됩니다. 원자료, compiled truth, append-only event ledger, typed links, graph-boosted search index 등을 구분하여 장기적으로 검증 가능한 second brain을 만드는 것이 목적입니다.

관련 파일:

- `src/wiki/gbrain_runtime.py`
- `src/wiki/governance.py`
- `wiki/index.md`
- `wiki/log.md`

## 5. Offline / Online / Live 실행 모델

Muchanipo는 local-first 제품이지만, 필요하면 provider CLI/API를 사용해 live research를 수행할 수 있습니다.

### 5.1 Offline mode

다음 경로는 외부 서버와 통신하지 않습니다.

```bash
muchanipo demo
muchanipo run "주제" --offline
MUCHANIPO_OFFLINE=1 muchanipo run "주제"
```

Offline mode 특성:

- 외부 API 호출 0건
- 사용자 검색어 전송 없음
- IP 전송 없음
- deterministic mock provider 사용
- 테스트/CI/데모에 적합
- 실제 논문/웹 검색 결과가 아니라 구조화된 fixture/mock evidence 사용

근거 문서: `docs/data-transmission-notice.md`

### 5.2 Online / Live mode

Online mode에서는 로컬 provider CLI나 API key를 통해 외부 서비스와 통신할 수 있습니다.

```bash
muchanipo run "주제" --online
MUCHANIPO_ONLINE=1 muchanipo run "주제"
MUCHANIPO_PREFER_CLI=1 python3 -m muchanipo serve --topic "주제" --pipeline full
```

통신 가능 서비스:

- OpenAlex
- Crossref
- Semantic Scholar
- Unpaywall
- arXiv
- CORE
- Anthropic / Google / OpenAI / Moonshot 등 LLM provider
- Plannotator HTTP gate

민감한 주제는 반드시 `--offline`을 명시하거나 개인정보를 익명화해야 합니다.

## 6. Provider 라우팅과 Fallback

Provider routing은 `docs/wiring-real-llm.md`와 `src/execution/gateway_v2.py`에 정의되어 있습니다. 제품 경로는 CLI-first입니다. Muchanipo가 Claude/Gemini/Kimi/Codex token file을 직접 읽는 것이 아니라, 설치된 CLI가 자기 login/session을 소유합니다. API key는 fallback 입력입니다.

기본 stage routing:

| Stage | Primary | Fallback chain |
| --- | --- | --- |
| intake | Gemini | gemini → anthropic → mock |
| interview | Anthropic | anthropic → gemini → mock |
| targeting | Gemini | gemini → anthropic → mock |
| research | Gemini | gemini → kimi → opencode → anthropic → mock |
| evidence | Kimi | kimi → gemini → opencode → anthropic → mock |
| council | Anthropic | anthropic → codex → kimi → gemini → opencode → mock |
| report | Anthropic | anthropic → gemini → opencode → mock |
| eval | Codex | codex → opencode → anthropic → mock |
| utilities / implementation_review | OpenCode | opencode → codex → mock / anthropic |

Budget control도 존재합니다.

```bash
MUCHANIPO_BUDGET_USD=0.5
```

Budget이 부족하면 gateway는 비용을 초과하지 않고 fallback chain을 따라 mock까지 내려갑니다. Audit log는 `vault/cost-log.jsonl`에 append-only로 기록됩니다.

## 7. Human-in-the-Loop 품질 게이트

Muchanipo는 자동화가 위험한 판단을 무조건 확신 있게 쓰지 않도록 HITL gate를 둡니다.

기본 품질 기준:

| 점수 | 상태 | 처리 |
| --- | --- | --- |
| 70+/100 | PASS | 직접 vault로 이동 |
| 50-69 | UNCERTAIN | signoff queue / human review |
| <50 | FAIL | discard + log |

v2.1에서 citation fidelity 11번째 축이 활성화되면 기준은 110점 scale로 바뀝니다.

- pass: 77/110
- uncertain: 55/110

HITL 관련 특성:

- Plannotator adapter는 plan/evidence/report gate에 사용될 수 있습니다.
- Offline fallback approval은 synthetic으로 표시됩니다.
- Live mode에서는 synthetic HITL gate를 거부합니다.
- Tauri app은 별도 Plannotator web page를 여는 대신 in-app constrained port를 사용합니다.

관련 파일:

- `src/hitl/plannotator_adapter.py`
- `src/hitl/plannotator_http.py`
- `app/muchanipo-tauri/src/plannotator-port/`
- `app/muchanipo-tauri/src/components/PlannotatorPlanEditor.tsx`
- `docs/reference-implementation-inventory.md`

## 8. 외부 Reference Project 통합 기준

Muchanipo는 외부 프로젝트 이름을 장식적으로 나열하지 않고, 각 reference가 실제 runtime behavior, adapter, dataset, vendored source, clean-room implementation, explicit license boundary 중 무엇으로 연결되는지 드러내는 방식을 택합니다.

핵심 원칙:

- `ready=false`인 reference를 완전 구현/99% 구현/상용 준비라고 표현하지 않습니다.
- `product_standard_covered=true`는 full upstream parity가 아니라 runnable runtime behavior, adapter, dataset, constrained port, license boundary가 있다는 뜻입니다.
- `muchanipo references --json`이 현재 source of truth입니다.
- License warning은 runtime이 없다는 뜻이 아니라, 배포·vendoring·추가 복제 시 compliance review가 필요하다는 뜻입니다.

6단계별 reference 배치:

| 단계 | 이름 | 주요 reference |
| --- | --- | --- |
| 1 | 인터뷰 / 요구사항 정리 | GPTaku show-me-the-prd, GStack office-hours |
| 2 | 목표 설정 / 연구 지도 | GStack plan-review, 학술 API, GBrain, Plannotator |
| 3 | 자료 수집 / 자동 연구 | Karpathy Autoresearch, InsightForge, MemPalace, 학술 API |
| 4 | 근거 검증 / 지식 정리 | GBrain, source-backed research, Plannotator |
| 5 | Council / 다중 관점 토론 | MiroFish, OASIS/CAMEL, Nemotron-Personas-Korea, HACHIMI, MAP-Elites |
| 6 | 보고서 작성 / 학습 축적 | ReACT report, Karpathy LLM Wiki Pattern, GBrain, GStack retro/learnings |

관련 문서:

- `docs/reference-projects.md`
- `docs/reference-implementation-inventory.md`

## 9. Run Artifact와 관측 가능성

정상 run은 기본적으로 아래 산출물을 만듭니다.

| Artifact | 설명 |
| --- | --- |
| `REPORT.md` | 최종 보고서 |
| `events.jsonl` | append-only 실행 이벤트 로그 |
| `summary.json` | run metadata와 artifact path |

기본 위치:

```text
~/.local/share/muchanipo/runs/<run-id>/
```

Tauri app과 CLI/TUI는 같은 event stream과 run summary를 기반으로 progress와 결과를 보여줍니다. `muchanipo runs --json --limit 5`로 최근 run summary를 scriptable하게 확인할 수 있습니다.

### 9.1 PASS 판정 기준

Muchanipo의 overnight/multi-agent 작업에서 **PASS는 UI heartbeat 또는 provider-call log만으로 선언하면 안 됩니다.** Heartbeat는 “프로세스가 살아 있음”을 보여주는 보조 신호일 뿐이며, 제품 동작이 올바르게 완료되었다는 증거가 아닙니다.

PASS를 선언하려면 최소한 아래 항목을 함께 확인해야 합니다.

| 필수 항목 | PASS에 필요한 증거 |
| --- | --- |
| Artifacts | `REPORT.md`, `events.jsonl`, `summary.json` 등 실행 산출물이 실제로 생성되어야 합니다. |
| Tests | 관련 Python/Rust/frontend 또는 focused regression test 결과가 있어야 합니다. |
| Source relevance | 수집된 source가 현재 연구 주제와 관련 있고, off-topic accepted source가 없어야 합니다. |
| Facet coverage | Korea adoption, market evidence, source channel 등 요구된 facet이 누락되지 않아야 합니다. |
| Event completion | `final_report`와 `done` 이벤트가 모두 있어야 합니다. |
| Incident report | 실패·부분성공·source-gate rejection·facet 부족이 있으면 incident report나 handoff note에 남겨야 합니다. |

권장 상태 표현:

- **PASS**: 위 필수 항목이 모두 충족됨.
- **PARTIAL**: 일부 개선 또는 일부 gate 통과가 있으나 facet/source/artifact/test 중 빠진 것이 있음.
- **FAIL**: 핵심 산출물, 테스트, source relevance, final completion event 중 하나 이상이 결여됨.
- **BLOCKED**: credential, 충돌 위험, 외부 승인, dependency 등으로 더 진행할 수 없음.

### 9.2 Incident report 표준

Incident report는 단순 에러 로그가 아니라 “다음 agent가 같은 실수를 반복하지 않도록 하는 감사 기록”입니다. 다음 경우 반드시 작성합니다.

- UI heartbeat는 있었지만 `final_report`/`done`이 없을 때
- provider call log는 있었지만 topic-relevant source가 부족할 때
- source gate가 off-topic source를 reject했거나, reject해야 할 source를 accept했을 때
- Korea adoption, market evidence, source channel/facet coverage가 부족할 때
- synthetic HITL approval 또는 offline fallback을 live PASS처럼 오해할 위험이 있을 때
- test는 통과했지만 product artifact가 누락되었을 때

권장 incident report 필드:

```markdown
## Incident
- Time:
- Agent / pane:
- Scope:
- Status: PASS / PARTIAL / FAIL / BLOCKED

## What happened
- Observed signals:
- Missing or misleading signals:

## Evidence
- Artifacts:
- Tests:
- Source relevance:
- Facet coverage:
- final_report/done:

## Root cause / hypothesis
- Confirmed facts:
- Hypotheses:

## Follow-up
- Required next action:
- Owner / next pane:
- Files or commands to inspect first:
```

### 9.3 Agent handoff protocol

Overnight multi-agent work must be resumable from Obsidian without relying on stale terminal state. Each substantial handoff should be written under:

```text
/Users/hyunjun/Documents/Hyunjun/Neobio/product/with-agent/muchanipo-p5int/
```

Handoff note에 반드시 포함할 항목:

- 작업 목적과 현재 상태
- 변경한 파일 또는 변경하지 않은 이유
- 실행한 검증 명령과 결과
- PASS/PARTIAL/FAIL/BLOCKED 판정과 그 근거
- 다음 agent가 먼저 읽어야 할 파일
- 금지 사항: push/merge/deploy/credential use/destructive cleanup 여부
- 남은 blocker와 다음 action

handoff는 “무엇을 했는지”보다 “다음 사람이 어떤 증거를 믿고 어디서 이어가야 하는지”를 우선합니다.

### 9.4 Hermes review loop protocol

Goals-mode overnight work는 네 pane이 병렬로 흩어져 일하는 것만으로 완료되지 않습니다. 필수 운영 루프는 다음 순서입니다.

```text
1. 네 pane 의견/검토를 수집한다.
2. Hermes가 네 입력을 종합해 하나의 결정으로 만들고 다음 구현/검증 작업을 수행한다.
3. Hermes 산출물을 다시 네 pane에 보내 검토받는다.
4. 네 pane review를 다시 수집한다.
5. Hermes가 다시 종합하고 다음 작업을 수행한다.
6. PASS/PARTIAL/FAIL/BLOCKED가 증거로 닫힐 때까지 반복한다.
```

이 루프는 “parallel isolated work”가 아니라 **collect → synthesize/work → review → synthesize/work → repeat** 구조입니다. 따라서 handoff note는 단순히 각 pane의 최종 로그를 붙이는 것이 아니라, 다음 항목을 감사 가능하게 남겨야 합니다.

- 어떤 네 pane 입력을 수집했는지
- Hermes가 어떤 결정을 내렸고 왜 그 결정을 택했는지
- Hermes가 실제로 수행한 작업과 생성한 artifact/test/source evidence
- 네 pane이 Hermes 산출물에 대해 제기한 review 항목
- 다음 반복에서 반영한 항목과 보류한 항목
- 반복 종료 판정과 PASS/PARTIAL/FAIL/BLOCKED 근거

네 pane review를 받기 전 Hermes 단독 작업은 “intermediate synthesis”일 수는 있어도 최종 PASS가 아닙니다.

Hermes synthesis record에는 매 반복마다 다음을 별도로 남깁니다.

- pane별 상태: `ACTIVE`, `idle done`, `stale/ignore`, `BLOCKED` 등
- 어떤 lane이 현재 gating item인지
- gating lane의 미완료 regression, incident, 또는 artifact gap
- Hermes가 선택한 next coordinated step과 선택하지 않은 대안
- 선택 근거: test-backed 여부, artifact-driven 여부, PASS guardrail 충족 여부
- four-pane review로 다시 돌려보낼 질문 또는 검토 요청

특히 어떤 pane이 `ACTIVE`이거나 regression/incident closure를 진행 중이면, Hermes synthesis는 그 lane을 PASS로 승격할 수 없습니다. 이 경우 handoff 상태는 `PARTIAL` 또는 `BLOCKED`로 남기고, gating item이 닫힌 뒤 다음 loop에서 다시 review를 수집해야 합니다.

## 10. Ontology-driven interview flow

Muchanipo의 interview는 정적 form이 아니라 사용자의 tacit knowledge, 판단 기준, 불확실한 가정, evidence standard를 끌어내는 semantic elicitation 과정입니다. 목표는 답변 목록을 만드는 것이 아니라 이후 research/council/report 단계가 사용할 ontology-like structure를 만드는 것입니다.

권장 ontology 구성 요소:

| 구성 요소 | 설명 |
| --- | --- |
| Entity | 사용자, 고객군, 제품, 시장, 논문, 규제기관, 경쟁사 등 |
| Relation | `targets`, `depends_on`, `contradicts`, `supports`, `requires_evidence_from` 등 |
| Facet | 시장성, adoption, 비용, 정확도, 규제, 공급망, channel, evidence quality 등 |
| Uncertainty | 답변 부족, 상충 근거, 낮은 confidence, source gap |
| Evidence standard | 어떤 출처가 충분한지, 어떤 출처는 배제해야 하는지 |

Interview 단계는 다음을 기록해야 합니다.

1. 사용자가 이미 알고 있는 사실과 추정의 분리
2. 결론에 영향을 주는 핵심 판단 기준
3. 후속 질문이 필요한 ambiguity
4. research query로 전환할 수 있는 facet별 정보 요구
5. evidence/citation 요구 수준
6. Council persona가 검토해야 할 반론 축

이렇게 만들어진 ontology-like 구조는 targeting map, source-gate, Council persona selection, report chapter mapping에 재사용되어야 합니다. 특정 vertical에만 맞는 hardcoded 질문으로 고정하지 않고, 사용자의 답변과 수집 자료에서 entity/relation/facet을 확장하는 방식이 바람직합니다.

### 10.1 Nemotron Personas ko_KR reference preservation

이 문서에서 goals-mode의 “persona” reference는 단순한 generic interview persona가 아니라, 우선적으로 NVIDIA NGC **Nemotron Personas Dataset ko_KR / Nemotron-Personas-Korea-Extended**를 뜻합니다.

- NGC URL: `https://catalog.ngc.nvidia.com/orgs/nvidia/teams/nemotron-personas/resources/nemotron-personas-dataset-ko_kr?version=0.0.1`
- Coordination note 기준 확인된 target: Korean-language synthetic persona dataset, version `0.0.1`, released `2026-04-23`, 약 `2.66 GB` compressed, `1M` records / `10M` personas, `51` fields, 17 provinces and 약 252 districts, adult 19+ personas, demographics/geography/OCEAN/persona descriptions, NeMo Data Designer + PGM + Gemma-based generation, NVIDIA Dataset License Agreement.

Muchanipo는 general-purpose 리서치 엔진이어야 하므로 특정 vertical에만 맞춘 hardcoded dispatch를 늘리면 안 됩니다. 그러나 이것은 사용자가 제공했거나 이전 작업에서 확인된 Nemotron ko_KR persona reference material을 임의로 삭제·축약·약화해도 된다는 뜻이 아닙니다.

운영 규칙:

- prior Korean persona reference가 필요하고 실제로 발견되면, 그 자료는 **as-is reference material**로 보존합니다. 이 goals loop에서는 해당 reference를 Nemotron Personas Dataset ko_KR / Nemotron-Personas-Korea-Extended로 해석합니다.
- 임의로 일부 필드를 prune/remove하거나 “일반화”라는 이유로 약화하지 않습니다.
- general-purpose 설계는 dispatch와 ontology derivation을 vertical-neutral하게 만드는 것이지, 사용자 제공 persona reference를 지우는 것이 아닙니다.
- Council persona selection은 topic/facet/evidence need에 따라 reference material을 사용할지 판단하되, 사용한다고 결정한 reference는 원문 provenance와 함께 유지합니다.
- 데이터셋 또는 사용자 제공 reference를 직접 쓰지 않은 경우에는 `schema-grounded, not dataset-sampled`처럼 경계를 명확히 표시합니다.
- 데이터셋 존재만으로 PASS를 주장하지 않습니다. 사용 전에는 NVIDIA Dataset License Agreement 검토, 다운로드 가능 여부, 로컬 저장 위치/크기, schema field mapping, PII/privacy posture, attribution/export 제한, integration boundary가 handoff나 incident record에 남아야 합니다.
- 실제 데이터 row를 seed/sample로 사용할 때는 `dataset-sampled`, schema만 참고할 때는 `schema-grounded`, 직접 사용하지 않았을 때는 `not dataset-sampled`처럼 evidence gate label을 분리합니다.
- ConceptGraph/ontology는 데이터셋에서 vertical preset을 hardcode하지 않고, 데이터셋은 Korean demographic/geographic/persona distribution을 검증·시뮬레이션·seed selection에 쓰는 reference boundary로 둡니다.

즉, “general-purpose”와 “Nemotron ko_KR persona reference 보존”은 충돌하지 않습니다. 전자는 pipeline logic의 중립성 원칙이고, 후자는 source/provenance/license/evidence 보존 원칙입니다.

## 11. Ctx2Skill-style skill evolution

Muchanipo의 skill evolution은 단순히 “좋았던 prompt를 저장”하는 기능이 아니라, 반복 작업에서 얻은 실패/성공 맥락을 재사용 가능한 skill로 승격하는 과정입니다. Coordination note에서 요구한 Ctx2Skill-style 흐름은 다음 다섯 역할로 정리합니다.

```text
Challenger → Reasoner → Judge → Proposer → Generator
```

| 역할 | Muchanipo에서의 책임 |
| --- | --- |
| Challenger | 기존 skill/prompt가 특정 사례에 과적합되었는지 공격적으로 반례를 찾음 |
| Reasoner | 실패 원인, 성공 조건, 필요한 context field를 분석함 |
| Judge | artifact/test/source relevance/facet coverage 기준으로 승격 가능성을 판정함 |
| Proposer | 새 Skill.md 또는 기존 skill patch proposal을 작성함 |
| Generator | 실제 skill 문서, test fixture, replay prompt, usage examples를 생성함 |

Skill 승격 전에 반드시 cross-time replay를 수행해야 합니다.

- 최근 성공 사례 1개만 보고 skill로 만들지 않습니다.
- 과거 실패·PARTIAL·incident report를 함께 replay합니다.
- domain-specific shortcut이 아닌, ontology/facet/evidence standard 중심으로 일반화합니다.
- Generator가 만든 Skill.md는 Judge가 artifact/test/source relevance/facet coverage 기준으로 다시 평가합니다.

Skill evolution handoff에는 최소한 아래를 남깁니다.

- 입력 context 요약
- 실패/성공 사례 링크
- replay한 과거 사례
- 승격/보류 판단
- Skill.md patch proposal 또는 생성 파일 경로
- known overfitting risk

## 12. 설치와 실행

### 12.1 요구사항

- Python 3.11+
- `httpx>=0.28`
- Online run용 optional provider CLI: Claude Code, Gemini, Kimi, Codex, OpenCode
- Optional API keys
- Optional Obsidian vault frontend
- Tauri 앱 개발 시 Node 18+, npm, Rust 1.77+, macOS Xcode Command Line Tools

### 12.2 CLI 빠른 시작

```bash
# Credential 없이 제품 smoke
muchanipo demo

# Terminal home
muchanipo

# Direct topic shortcut
muchanipo "딸기 농가용 저비용 분자진단 키트 시장성"

# 명시적 offline run
muchanipo run "딸기 진단키트 시장성" --offline

# TUI mode
muchanipo tui "딸기 진단키트 시장성" --online

# Readiness / status
muchanipo doctor
muchanipo status
muchanipo runs
muchanipo contracts
muchanipo references
```

### 12.3 Tauri 앱 개발 실행

```bash
cd app/muchanipo-tauri
npm install
npm run tauri dev
```

### 12.4 Tauri 앱 릴리스 빌드

```bash
cd app/muchanipo-tauri
npm install
npm run tauri build
# → src-tauri/target/release/bundle/macos/Muchanipo.app
```

## 13. 설정과 환경변수

| 변수 | 설명 |
| --- | --- |
| `MUCHANIPO_OFFLINE=1` | 강제 오프라인 모드 |
| `MUCHANIPO_ONLINE=1` | 강제 온라인 모드 |
| `MUCHANIPO_PREFER_CLI=1` | 설치된 provider CLI 우선 사용 |
| `MUCHANIPO_PREFER_CLI=0` | provider CLI 자동 사용 비활성화 |
| `MUCHANIPO_CONTACT_EMAIL` | 학술 API 호출 시 사용할 contact email |
| `MUCHANIPO_BUDGET_USD` | research hard budget cap |
| `PLANNOTATOR_API_KEY` | Plannotator HTTP HITL gate 사용 |
| `PLANNOTATOR_ENDPOINT` | Plannotator endpoint override |
| `PLANNOTATOR_OFFLINE=1` | API key 없는 synthetic offline HITL 결과 사용 |

Provider별 offline trigger도 존재합니다.

| Provider | Offline trigger |
| --- | --- |
| Anthropic | CLI/API unavailable 또는 `ANTHROPIC_OFFLINE=1` |
| Gemini | CLI/API unavailable 또는 `GEMINI_OFFLINE=1` |
| Kimi | CLI/API unavailable 또는 `KIMI_OFFLINE=1` |
| Codex | CLI/API unavailable 또는 `CODEX_OFFLINE=1` |

## 14. 데이터 전송과 개인정보 주의사항

Offline mode에서는 외부 API 호출, 검색어 전송, IP 전송이 없습니다. Online mode에서는 연구 주제와 파생 검색어, prompt context, DOI/contact email, Plannotator payload가 외부 서비스로 전송될 수 있습니다.

민감한 주제에서는 다음 원칙을 따릅니다.

1. 가능한 경우 `--offline`을 명시합니다.
2. 개인정보를 제거하거나 익명화합니다.
3. 학술 API를 사용할 경우 `MUCHANIPO_CONTACT_EMAIL`을 실제 운영 email로 설정합니다.
4. Plannotator HTTP gate를 사용할 때는 전송되는 plan/brief/evidence/report payload를 사전에 확인합니다.

자세한 내용은 `docs/data-transmission-notice.md`를 확인합니다.

## 15. 코드베이스 구조

주요 디렉토리:

```text
muchanipo-p5int/
├── src/
│   ├── muchanipo/              # CLI/server/event entrypoint
│   ├── pipeline/               # lifecycle, runner, idea-to-council pipeline
│   ├── intake/                 # idea capture/normalization
│   ├── interview/              # interview/PRD/brief generation
│   ├── targeting/              # research targeting map
│   ├── research/               # source research, academic adapters, autoresearch
│   ├── search/                 # InsightForge/ReACT style search/report helpers
│   ├── evidence/               # evidence refs, provenance, quality checks
│   ├── council/                # persona generation, council session, diversity
│   ├── report/                 # chapter mapping and pyramid formatting
│   ├── hitl/                   # Plannotator/HITL adapters
│   ├── execution/providers/    # Claude/Gemini/Kimi/Codex/OpenCode/mock providers
│   ├── runtime/                # live mode, path utilities, plugin loader
│   └── wiki/                   # GBrain/raw-wiki governance runtime
├── app/muchanipo-tauri/        # Tauri desktop app
├── docs/                       # contracts, provider wiring, reference inventory
├── raw/                        # human-owned source drop zone
├── wiki/                       # LLM-owned compiled knowledge
├── vault/                      # persona/insight seeds and local memory
└── reports/                    # generated reports
```

## 16. 제품 상태와 알려진 한계

현재 문서 기준으로 Stage 1-6은 runtime-backed이지만 모든 reference가 full upstream parity를 달성한 것은 아닙니다. 일부 reference는 license/compliance boundary 때문에 full vendoring이 아니라 local adaptation, constrained port, dataset, adapter로 표현됩니다.

명시된 한계:

- Tauri app에 streaming token UI는 아직 없습니다. Council stream은 round-level event로 접힙니다.
- Plannotator HITL은 API key가 없으면 markdown/offline/synthetic path를 사용합니다.
- Citation grounder는 character + n-gram 중심이며 semantic embedding 비교는 별도 Phase 3 ticket 성격입니다.
- Live provider/HITL behavior는 offline deterministic test와 별도로 opt-in live smoke가 필요합니다.

## 17. 운영 체크리스트

제품 사용 전:

- [ ] `muchanipo doctor`로 로컬 readiness 확인
- [ ] `muchanipo status`로 provider CLI/API 상태 확인
- [ ] 민감 주제라면 `--offline` 사용
- [ ] online run이면 `MUCHANIPO_CONTACT_EMAIL` 설정
- [ ] live provider claim 전 opt-in live smoke 수행
- [ ] PASS claim 전 artifacts/tests/source relevance/facet coverage/final_report/done 확인
- [ ] PARTIAL/FAIL/BLOCKED이면 Obsidian handoff 또는 incident report 작성

릴리스/품질 확인:

```bash
bash scripts/release_check.sh
muchanipo contracts --json
muchanipo references --json
muchanipo demo
```

Tauri 앱 확인:

```bash
cd app/muchanipo-tauri
npm install
npm run tauri dev
```

## 18. 핵심 메시지

Muchanipo는 단순한 챗봇이나 보고서 생성기가 아닙니다. 제품 아이디어와 연구 주제를 받아, 요구사항 정리·자료 수집·근거 검증·다중 관점 토론·보고서 생성·지식 축적까지 하나의 파이프라인으로 묶는 로컬 우선 자율 리서치 시스템입니다. CLI/TUI는 제품의 중심 실행 경로이고, Tauri 앱은 같은 runtime을 더 시각적으로 제어하고 확인하는 데스크톱 shell입니다.

가장 중요한 제품 약속은 세 가지입니다.

1. **오프라인에서도 끝까지 동작한다.**
2. **온라인에서는 provider CLI/API를 stage별로 안전하게 라우팅한다.**
3. **근거와 사람 검토 없이 확신 있는 결론으로 포장하지 않는다.**
