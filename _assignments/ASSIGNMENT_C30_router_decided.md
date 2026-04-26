# C30 Model Router — Decided Design (4-agent 합성)

**작성:** 2026-04-26
**참조:** `_design/c30/{api,impl,cost,config}_proposal_*.md` (1454 LOC, 4 worker)
**핵심:** 4 proposal 모두 다른 layer를 다뤄 충돌 없음 → 모두 수용 + 통합

---

## 4 Layer 합성

```
┌─────────────────────────────────────────────────┐
│ User code                                       │
│   router.call(Stage.PHASE0_INTERVIEW, prompt)   │ ← Worker 1 API
└─────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────┐
│ src/router/core.py — stage 라우팅 + fallback   │ ← Worker 2 모듈 분리
│   (모듈 1개 = 책임 1개, <150 LOC)               │
└─────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────┐
│ src/router/cost.py — 5-step control plane      │ ← Worker 3 cost
│   estimate → reserve → dispatch → reconcile →  │
│   log (atomic, typed failures)                 │
└─────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────┐
│ src/router/providers/{anthropic,openai,ollama,│ ← Worker 2 provider
│   codex}.py — 한 함수 = 한 transport            │
└─────────────────────────────────────────────────┘
                    ↑                            ↑
              config/models.json            secrets (env)
              (profiles, stage routing,
               health, budget, observ)         ← Worker 4 config
```

---

## Module structure (확정)

```
src/router/
  __init__.py            — public exports (ModelRouter, Stage, errors)
  stages.py              — Stage 상수 (Worker 1)
  core.py                — ModelRouter 라우팅 로직 (Worker 2)
  cost.py                — 5-step control plane (Worker 3)
  config.py              — models.json 로더 + profile resolver (Worker 4)
  health.py              — provider health check + cache (Worker 4)
  errors.py              — RouterError, BudgetExceeded, AllProvidersDown 등 (Worker 1)
  providers/
    __init__.py
    base.py              — ProviderResult dataclass
    anthropic.py         — call(spec, prompt) → ProviderResult
    openai.py
    ollama.py
    codex_cli.py
    mock.py              — test용 (Worker 2 first-class)
```

---

## API 시그니처 (Worker 1 채택)

```python
from router import ModelRouter, Stage

router = ModelRouter.from_env()  # profile = $MUCHANIPO_PROFILE or "dev"

# 동기 (default)
result = router.call(Stage.COUNCIL_PERSONA, prompt="...", max_tokens=2000)
# result: {"text": str, "model": str, "cost_usd": float, "is_fallback": bool}

# 비동기 (async mirror)
result = await router.acall(Stage.REPORT_COMPOSER, prompt="...")

# session 비용 누적은 자동
print(router.session_cost())  # {"total_usd": 1.23, "by_stage": {...}}
```

## Stage 카탈로그

| Stage | Primary | Fallback chain |
|---|---|---|
| `PHASE0_INTERVIEW` | sonnet-4.6 | opus-4.7 |
| `COUNCIL_PERSONA` | local-qwen3 / deepseek-v4 | sonnet-4.6 |
| `COUNCIL_REBUTTAL` | sonnet-4.6 | opus-4.7 |
| `EVAL_AXIS` | sonnet-4.6 | opus-4.7 |
| `FRAMEWORK_APPLY` | sonnet-4.6 | kimi-k2 → opus-4.7 |
| `REPORT_COMPOSER` | opus-4.7 | gpt-5 |
| `CODE_REVIEW` | codex (gpt-5.3-codex) | claude-sonnet |
| `DREAM_CYCLE` | local-qwen3 | sonnet-4.6 |

## Cost control plane (Worker 3 채택)

매 호출 5 step:
1. **Estimate**: tokenizer로 input 토큰 추정 + max_tokens × output 가격
2. **Reserve**: session ledger에 atomic counter (`vault/cost-log.jsonl` + `.cost-lock` filelock)
3. **Dispatch**: provider call
4. **Reconcile**: 응답 usage 필드로 reservation 정정
5. **Log**: ledger record 영구 저장 (estimate + actual + reason)

session cap soft warn 50% / 75% / hard stop 95%. cap 초과 시 `BudgetExceeded` raise (사용자 코드가 catch 가능).

## Config schema (Worker 4 채택, 축약)

`config/models.json` profiles 분리 (dev/staging/prod). secrets는 `${ANTHROPIC_API_KEY}` 식 env reference. profile은 `$MUCHANIPO_PROFILE` 또는 `--profile` 플래그로 선택.

---

## 구현 sprint 분배 (다음 단계)

C30 design 끝남. 구현은 C30-impl sprint에서 4 lane 병렬:

| Lane | 담당 | 산출 |
|---|---|---|
| `c30-impl-core` (claude) | core.py + stages.py + errors.py + tests | 50+ LOC |
| `c30-impl-cost` (codex) | cost.py + ledger + atomic counter + tests | 100+ LOC |
| `c30-impl-providers` (claude) | providers/{anthropic,openai,ollama,codex,mock}.py | 200+ LOC |
| `c30-impl-config` (codex) | config.py + health.py + models.json + tests | 100+ LOC |

기존 `src/runtime/model-router.py` (1200 LOC monolith)는 deprecated stub로 유지하다가 마지막 sprint에서 제거.

---

## 결정 사항 — 사용자 확인 항목

다음 4개 결정:
1. **Profile 기본값** — `dev` / `prod`?
   - 권고: env var `MUCHANIPO_PROFILE` 우선, 없으면 `dev`
2. **Local 모델 우선순위** — Qwen3 first vs DeepSeek V4 first?
   - 권고: Qwen3-30B-A3B (이미 사용자 머신에 깔려있다면)
3. **Session budget default** — $5? $10? $20?
   - 권고: dev `$5`, prod `$50`
4. **기존 model-router.py 처리** — keep / deprecate / 즉시 삭제?
   - 권고: deprecate (raise DeprecationWarning) → 다음 sprint 종료 시 삭제

확정되면 구현 sprint (C30-impl) 4 worker 병렬 시작.
