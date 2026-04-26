# C30 — Model Router 설계 Multi-Agent 토론 Sprint

**작성:** 2026-04-26
**도구:** GitButler 4 virtual branches × 2 claude + 2 codex 토론
**목표:** 단계별 모델 라우팅 인프라 설계 — 각 worker가 자기 관점에서 proposal 제출 → 메인이 합성

## 최종 산출 (사용자 요구)

```
Phase 0 Interview          → Sonnet 4.6
Council 페르소나 (대량)     → 로컬 Qwen3 / DeepSeek V4
Council 반론·검증          → Sonnet 4.6
Eval 11/13 axis            → Sonnet 4.6
Framework 적용             → Sonnet 4.6 또는 Kimi K2
Report Composer (MBB 30p)  → Opus 4.7 또는 GPT-5
Code review                → Codex
Dream Cycle                → 로컬 Qwen3
```

핵심 기능:
1. stage → primary model + fallback chain mapping
2. 비용 트래킹 (call count + tokens + $)
3. session 비용 캡 (예: $5/세션)
4. rate limit + 폴백 (로컬 down → cloud)
5. 로컬·원격 endpoint 추상화

---

## 워커 분배 (각자 자기 관점에서 proposal MD 작성)

각 worker는 자기 branch의 `_design/c30/<name>.md`에 design proposal 작성.
**구현은 안 함 — 설계 토론만.** 다른 worker proposal 손대지 말 것.

### Worker 1 (claude) — c30-router-claude-api · API 인터페이스

**관점:** Python 사용자 입장에서 가장 깨끗한 API.

**산출:** `_design/c30/api_proposal_claude.md`
- `ModelRouter` 클래스 시그니처 (`__init__`, `for_stage(stage) -> ModelSpec`, `call(stage, prompt, **kw) -> str`)
- `ModelSpec` dataclass 필드 (provider, model_id, endpoint, context_limit, max_tokens, temperature)
- 단계별 호출 예시 — Phase 0 Interview에서 어떻게 import + 호출?
- 비동기 vs 동기 — 어느 쪽 default?
- 에러 클래스 (RouterError, BudgetExceeded, AllProvidersDown 등)
- 합쳐 50-80 LOC pseudo-code

**완료 표시:** `touch _research/.c30-locks/worker-1.done`

---

### Worker 2 (claude) — c30-router-claude-impl · Implementation skeleton

**관점:** 실제 동작 가능한 minimal skeleton.

**산출:** `_design/c30/impl_proposal_claude.md`
- 필수 모듈 분리: `router.py` (core), `providers/anthropic.py`, `providers/openai.py`, `providers/ollama.py`, `providers/codex_cli.py`
- 비용 트래킹 어디서? (call wrapper 또는 별도 cost_meter)
- 로깅 — `vault/cost-log.jsonl` append schema
- session ID 어디서 받기? (env var? 파라미터?)
- session 비용 캡 hit 시 동작 (raise / fallback to free / pause?)
- 폴백 chain 처리 패턴 (chain of responsibility / try-except / decorator)
- Test 전략 — 실제 endpoint 안 치고 어떻게 검증? (mock provider)
- 합쳐 100-150 LOC pseudo-code

**완료 표시:** `touch _research/.c30-locks/worker-2.done`

---

### Worker 3 (codex) — c30-router-codex-cost · Cost & Fallback 정확성

**관점:** 비용 계산 정확성, race condition, edge case.

**산출:** `_design/c30/cost_proposal_codex.md`
- 토큰 카운트 — provider별 다른 tokenizer (anthropic/openai/llama). 어떻게 통일?
- 비용 계산 공식 — input·output 토큰 가격, cache discount, batch discount
- session cap 설계 — soft warn vs hard stop, 50% / 75% / 95% threshold
- 동시 호출 시 cost 계산 race — atomic counter 또는 lock
- 폴백 trigger 정책 — 1차 timeout? rate limit 429? cap 초과? 모두 다른 chain?
- 모델 가용성 health check (Ollama down, API key 만료) 주기 + cache TTL
- 비용 회계 정확성 — provider 응답에서 usage 필드 누락 시 fallback estimate
- recommendations: 비용 통제 best practices 5+

**완료 표시:** `touch _research/.c30-locks/worker-3.done`

---

### Worker 4 (codex) — c30-router-codex-config · Config schema & ops

**관점:** 운영 친화도 — config 변경 쉬움, 디버깅 쉬움, 환경 분리.

**산출:** `_design/c30/config_proposal_codex.md`
- `config/models.json` schema 예시 (전체 stage × primary + fallback chain)
- env var override 우선순위 — config < env < CLI flag?
- secrets 관리 — API key 어디서 (env? secrets manager? .env)
- profile 분리 — dev / staging / prod 별 다른 모델 매핑?
- model 추가 절차 — 새 provider 5분 안에 추가하려면?
- 모델 deprecation 처리 — Opus 4.7이 끝나면 자동 4.8로 fallback?
- observability — 어떤 metric 노출? (call count by stage, p50/p99 latency, cost by stage)
- recommendations: ops 친화도 5+

**완료 표시:** `touch _research/.c30-locks/worker-4.done`

---

## 메인 thread (사용자 + Claude)

각 워커 4 done 차면:
1. 4 proposal MD 모두 읽기
2. 각자 강점·약점·중복 식별
3. 합성 design doc `_assignments/ASSIGNMENT_C30_router_decided.md` 작성
4. 사용자 confirm 후 구현 sprint (별도 PR)

---

## 공통 검증

- **회귀**: pytest 269 PASS 유지 (이번 sprint는 design only — 코드 변경 없음)
- **MD only**: 각 worker는 `.md` 파일만 추가. `.py` 수정 금지.
- **branch isolation**: 자기 lane만 수정. 다른 lane 손대지 말 것.

## 종료 표시

`_research/.c30-locks/worker-{1..4}.done` 4개 모두 생성 후 메인이 합성.
