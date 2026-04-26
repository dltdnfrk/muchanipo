# C30 Worker 2 — Implementation Skeleton Proposal

**Author:** worker-2 (claude, c30-router-claude-impl lane)
**Scope:** MD-only design. Minimal yet runnable skeleton for the new `ModelRouter`.
**Aligned with assignment:** `_assignments/ASSIGNMENT_C30_model_router.md`
**Reference for legacy code:** `src/runtime/model-router.py` (현재 1,200 LOC monolith).

---

## 0. 설계 철학 — "minimal vertical slice"

현재 `src/runtime/model-router.py`는 single-file 1,200 LOC monolith로 router + 모든 provider + cost + CLI가 한 곳에 뭉쳐 있다. C30에서는 **stage→provider 매핑을 1차 시민으로 승격**하고, provider/cost/log/session을 **수평 분리**하여 각 책임이 한 페이지(<150 LOC)에 끝나도록 만든다. 이렇게 해야 worker-1의 API proposal과 worker-3·4의 cost/config proposal을 부담 없이 끼워 넣을 수 있다.

핵심 원칙 5개:
1. **모듈 1개 = 책임 1개.** core/router는 stage 라우팅과 fallback chain 결정만 담당.
2. **provider는 한 함수 = 한 transport.** anthropic/openai/ollama/codex 모두 `def call(spec, prompt, **kw) -> ProviderResult` 한 함수만 export.
3. **비용은 호출 wrapper에서 단일 지점 측정.** provider 안에서 직접 회계하지 않는다 (race 방지·테스트 용이).
4. **session 캡과 폴백은 같은 decision loop.** "지금 호출 가능한가?"를 한 번만 판단.
5. **Mock provider가 first-class.** 실제 endpoint를 치지 않고도 269 PASS를 유지.

---

## 1. 모듈 분리 (필수)

```
src/runtime/router/
├── __init__.py            # public re-export: ModelRouter, ModelSpec, errors
├── router.py              # core: stage→spec 결정 + fallback decision loop (~120 LOC)
├── spec.py                # ModelSpec dataclass + Stage Literal (~40 LOC)
├── errors.py              # RouterError 계층 (~30 LOC)
├── cost_meter.py          # CostMeter (atomic add, session cap 검사) (~80 LOC)
├── session.py             # SessionContext (id, started_at, budget_usd) (~40 LOC)
├── log_sink.py            # JSONL append-only sink → vault/cost-log.jsonl (~50 LOC)
└── providers/
    ├── __init__.py        # PROVIDERS registry: name → call fn
    ├── base.py            # ProviderResult dataclass + Protocol (~40 LOC)
    ├── anthropic.py       # Sonnet 4.6 / Opus 4.7 (~80 LOC)
    ├── openai.py          # GPT-5 / Codex remote (~70 LOC)
    ├── ollama.py          # Qwen3 / DeepSeek V4 local (~60 LOC)
    ├── codex_cli.py       # Codex CLI subprocess (~70 LOC)
    └── mock.py            # 결정론적 dummy — pytest 전용 (~40 LOC)
```

**Why this split (worker-1 API proposal과의 인터페이스):**
- `router.py`는 worker-1의 `ModelRouter.for_stage()` / `.call()` 시그니처를 그대로 구현하면 끝나는 얇은 facade.
- `spec.py`는 worker-1·worker-4가 동시에 참조하는 단일 진실원. config schema(worker-4)는 이 dataclass로 deserialize된다.
- `cost_meter.py` + `log_sink.py`는 worker-3의 cost 정책을 수용하기 위한 hook point.

---

## 2. 핵심 데이터 흐름

```
caller
  │  router.call("phase0_interview", prompt)
  ▼
ModelRouter._decide(stage, attempt=0)
  │  → ModelSpec(primary)
  ▼
CostMeter.preflight(session, spec, est_tokens)
  │  ├─ OK → 다음
  │  ├─ SOFT_WARN → 로깅 후 진행
  │  └─ HARD_STOP → BudgetExceeded raise (no provider call)
  ▼
PROVIDERS[spec.provider].call(spec, prompt, **kw)
  │  ├─ ProviderResult(ok=True, usage=...) → CostMeter.commit() → log_sink.write()
  │  └─ raise ProviderTimeout/RateLimited/Unavailable
  ▼
on raise: router._decide(stage, attempt+1) → next fallback in chain
```

`router.py`에서 한 번만 결정 loop를 돌리고, 각 provider는 transport에만 집중한다. **cost commit은 성공한 호출에만**, log_sink는 성공·실패 모두 기록한다 (실패 시 `usage=None`).

---

## 3. 비용 트래킹 위치 (cost_meter.py가 단일 지점)

3가지 호출 경로 (provider 직접 호출 / fallback 호출 / mock) 모두 `router._invoke_with_meter()` 한 함수를 통과한다.

```python
class CostMeter:
    def __init__(self, session: SessionContext, sink: LogSink):
        self._session = session
        self._sink = sink
        self._lock = threading.Lock()  # 단일 프로세스 내 race 방지
        self._spent_usd = 0.0
        self._calls = 0

    def preflight(self, spec: ModelSpec, est_input_tokens: int) -> Decision:
        # worker-3가 채울 정확한 정책: soft_warn 75%, hard_stop 100%
        with self._lock:
            est_cost = _estimate_cost(spec, est_input_tokens)
            projected = self._spent_usd + est_cost
            if projected > self._session.budget_usd:
                return Decision.HARD_STOP
            if projected > 0.75 * self._session.budget_usd:
                return Decision.SOFT_WARN
            return Decision.OK

    def commit(self, spec: ModelSpec, usage: Usage) -> float:
        # provider 응답의 실제 usage로 정산
        with self._lock:
            actual = _price(spec, usage)
            self._spent_usd += actual
            self._calls += 1
            return actual
```

**왜 wrapper 단일 지점인가?**
- provider 안에서 회계하면 mock에서도 회계 로직을 복제해야 한다 (테스트 신뢰도 ↓).
- worker-3의 race 시나리오 (동시 호출)를 한 곳의 lock으로 끝낸다.
- worker-4의 cost rate 변경 시 provider를 건드릴 필요가 없다.

---

## 4. 로깅 — `vault/cost-log.jsonl` append schema

한 줄 = 한 호출. 후속 분석/Council eval 11/13 axis가 이 JSONL을 그대로 grep한다.

```json
{
  "ts": "2026-04-26T08:14:33.012Z",
  "session_id": "c2-17-resume-001",
  "stage": "council_persona_bulk",
  "attempt": 0,
  "spec": {"provider": "ollama", "model_id": "qwen3:32b", "endpoint": "http://localhost:11434"},
  "outcome": "ok",
  "elapsed_ms": 1842,
  "usage": {"input_tokens": 612, "output_tokens": 1480, "cache_read_tokens": 0},
  "cost_usd": 0.0,
  "session_spent_usd": 0.4123,
  "session_budget_usd": 5.0,
  "fallback_from": null,
  "error": null
}
```

규칙:
- **append-only.** truncation/rotation은 일 단위 cron이 별도로 처리.
- **outcome ∈ {ok, fallback, error, budget_blocked}**.
- **fallback_from**: 폴백 hop마다 직전 spec.model_id 기록 → chain 재구성 가능.
- **session_spent_usd**: commit 직후 누적. dashboard용 derived 값이지만 한 줄로 답을 주기 위해 미리 박는다.
- **PII 미포함.** prompt/response 본문은 별도 vault 디렉토리에 저장.

---

## 5. Session ID 어디서 받는가?

3-tier resolution (precedence 우선순위 ↑):

1. **명시 파라미터** — `ModelRouter.call(stage, prompt, session_id="...")`. 테스트·script용.
2. **`SessionContext` 컨텍스트 매니저**:
   ```python
   with new_session(budget_usd=5.0, label="c2-17-resume") as sess:
       router.call("phase0_interview", prompt)  # sess 자동 주입
   ```
3. **env var** `MUCHANIPO_SESSION_ID` — orchestrator가 하위 프로세스로 전파. 없으면 `f"adhoc-{uuid4().hex[:8]}"` 폴백.

`SessionContext`는 `contextvars.ContextVar`에 저장 → 멀티스레드/asyncio 안전. 이렇게 하면 worker-1의 API proposal에서 session_id를 시그니처에 강제로 노출하지 않아도 된다.

---

## 6. Session 비용 캡 hit 시 동작

worker-3의 정책 디테일은 별도 proposal에서 결정되겠지만, **skeleton의 default behavior**는:

| 임계 | 동작 |
|------|------|
| < 75% | 정상 호출 |
| 75–95% | 호출은 진행. log에 `"warn":"approaching_cap"` 기록 + stderr `[BUDGET WARN]` 1줄 |
| 95–100% | 동일하지만 `"warn":"critical_cap"` |
| ≥ 100% (preflight) | `BudgetExceeded` raise, **provider 호출하지 않음**. router는 fallback chain에서 *cheaper* provider만 재시도 (`spec.tier <= current.tier`). cheaper 후보가 없으면 그대로 propagate. |
| 100% (commit 후 사후 발견) | log에 `"warn":"overshoot"` + 다음 호출부터 hard_stop. 사후 환불은 안 함. |

**핵심**: hard_stop은 raise — silent pause/fallback to free는 안 함. 사용자가 명시적으로 "다음 단계 LLM 없이 진행" 하도록 결정. (Council 페르소나 대량 단계처럼 일부 단계가 빠지면 산출물 자체가 무효해지는 케이스를 보호)

---

## 7. 폴백 chain 처리 패턴

**선택: try/except 기반 명시적 loop** (chain-of-responsibility 객체 그래프 / decorator stack 둘 다 검토 후 기각).

```python
def call(self, stage: Stage, prompt: str, **kw) -> str:
    chain = self._spec_chain(stage)  # [primary, *fallbacks]
    last_exc: Optional[Exception] = None
    for attempt, spec in enumerate(chain):
        decision = self._cost.preflight(spec, _estimate_input(prompt))
        if decision is Decision.HARD_STOP:
            if not self._has_cheaper_after(chain, attempt, spec):
                raise BudgetExceeded(stage, self._cost.snapshot())
            continue  # 다음 폴백 시도
        try:
            result = PROVIDERS[spec.provider].call(spec, prompt, **kw)
            self._cost.commit(spec, result.usage)
            self._log.write(_record(stage, attempt, spec, result, self._cost))
            return result.text
        except (ProviderTimeout, RateLimited, ProviderUnavailable) as exc:
            last_exc = exc
            self._log.write(_record(stage, attempt, spec, None, self._cost, error=exc))
            continue
    raise AllProvidersDown(stage, chain) from last_exc
```

**왜 decorator/CoR 객체가 아닌가?**
- chain은 **stage마다 다르고 config로 변경**된다. 객체 그래프는 reload 비용이 크다.
- try/except는 stack trace가 자연스럽고 PDB로 잡기 쉽다 (worker-3가 race condition 디버깅할 때).
- chain은 보통 길이 2–3. for loop 가독성 > 추상화 이득.

**예외 분류 (errors.py):**
```python
class RouterError(Exception): ...
class BudgetExceeded(RouterError): ...
class ProviderUnavailable(RouterError): ...   # endpoint down, dns fail, codex CLI missing
class RateLimited(ProviderUnavailable): ...   # 429 — 폴백 trigger
class ProviderTimeout(ProviderUnavailable): ...
class AllProvidersDown(RouterError): ...      # chain 전부 소진
class ConfigError(RouterError): ...           # spec resolution 단계
```

---

## 8. Test 전략 — mock provider first-class

**269 PASS 회귀 보호의 핵심.** 실제 endpoint는 1개도 안 친다.

### 8.1 `providers/mock.py`
```python
@dataclass
class MockProvider:
    responses: dict[str, str] = field(default_factory=dict)  # stage → canned text
    fail_next: deque = field(default_factory=deque)          # 강제 실패 시퀀스
    usage: Usage = Usage(input_tokens=100, output_tokens=200)

    def call(self, spec: ModelSpec, prompt: str, **kw) -> ProviderResult:
        if self.fail_next:
            raise self.fail_next.popleft()
        return ProviderResult(text=self.responses.get(spec.model_id, "MOCK"), usage=self.usage)
```

### 8.2 fixture 패턴
```python
@pytest.fixture
def router(tmp_path):
    sink = LogSink(tmp_path / "cost-log.jsonl")
    sess = SessionContext(id="t", budget_usd=1.0)
    cfg = load_test_config()  # primary=mock:opus, fallback=mock:sonnet
    return ModelRouter(config=cfg, session=sess, log=sink, providers={"mock": MockProvider()})
```

### 8.3 회귀 가드 6개 (필수 케이스)
1. `test_route_returns_primary_spec_for_known_stage`
2. `test_fallback_on_rate_limited_succeeds_on_second_spec`
3. `test_all_providers_down_raises_after_chain_exhausted`
4. `test_budget_exceeded_blocks_call_before_provider_invocation`
5. `test_cost_meter_aggregates_concurrent_commits` (threading.Thread×8, 동일 session)
6. `test_log_sink_records_fallback_with_provenance` (fallback_from 필드 검증)

### 8.4 통합 (선택, opt-in marker)
- `pytest -m live_ollama` — Ollama가 실제로 떠 있을 때만. CI에서는 skip.
- `pytest -m live_anthropic` — `ANTHROPIC_API_KEY` 있을 때만.

---

## 9. 100–150 LOC pseudo-code (router.py 핵심)

```python
# src/runtime/router/router.py
from __future__ import annotations
import logging
from typing import Optional
from .spec import ModelSpec, Stage
from .errors import (
    AllProvidersDown, BudgetExceeded, ProviderUnavailable, ConfigError,
)
from .cost_meter import CostMeter, Decision
from .session import SessionContext, current_session
from .log_sink import LogSink, build_record
from .providers import PROVIDERS

log = logging.getLogger(__name__)


class ModelRouter:
    def __init__(
        self,
        config: dict,
        *,
        session: Optional[SessionContext] = None,
        log_sink: Optional[LogSink] = None,
        providers: Optional[dict] = None,
    ):
        self._config = config
        self._session = session or current_session()
        self._log = log_sink or LogSink.default()
        self._providers = providers or PROVIDERS
        self._cost = CostMeter(self._session, self._log)

    # --- public API (worker-1 proposal 시그니처와 일치) ---------------------

    def for_stage(self, stage: Stage) -> ModelSpec:
        chain = self._spec_chain(stage)
        return chain[0]

    def call(self, stage: Stage, prompt: str, **kw) -> str:
        chain = self._spec_chain(stage)
        last_exc: Optional[Exception] = None

        for attempt, spec in enumerate(chain):
            decision = self._cost.preflight(spec, _estimate_input(prompt))

            if decision is Decision.HARD_STOP:
                if not self._has_cheaper_after(chain, attempt, spec):
                    self._log.write(build_record(
                        stage, attempt, spec, result=None,
                        cost=self._cost, outcome="budget_blocked",
                    ))
                    raise BudgetExceeded(stage, self._cost.snapshot())
                continue  # 다음 폴백 시도

            if decision is Decision.SOFT_WARN:
                log.warning("[BUDGET WARN] %s spent=%.4f cap=%.2f",
                            self._session.id, self._cost.spent, self._session.budget_usd)

            provider = self._providers.get(spec.provider)
            if provider is None:
                raise ConfigError(f"unknown provider: {spec.provider}")

            try:
                result = provider.call(spec, prompt, **kw)
                self._cost.commit(spec, result.usage)
                self._log.write(build_record(
                    stage, attempt, spec, result, self._cost, outcome="ok",
                    fallback_from=chain[attempt - 1].model_id if attempt else None,
                ))
                return result.text
            except ProviderUnavailable as exc:
                last_exc = exc
                self._log.write(build_record(
                    stage, attempt, spec, result=None, cost=self._cost,
                    outcome="error", error=exc,
                ))
                continue

        raise AllProvidersDown(stage, chain) from last_exc

    # --- internal -----------------------------------------------------------

    def _spec_chain(self, stage: Stage) -> list[ModelSpec]:
        entry = self._config["routing"].get(stage)
        if entry is None:
            raise ConfigError(f"stage not configured: {stage}")
        primary = ModelSpec.from_dict(entry["primary"])
        fallbacks = [ModelSpec.from_dict(f) for f in entry.get("fallback", [])]
        return [primary, *fallbacks]

    def _has_cheaper_after(self, chain, idx, spec) -> bool:
        return any(s.tier <= spec.tier for s in chain[idx + 1:])


def _estimate_input(prompt: str) -> int:
    return max(1, len(prompt) // 3)  # 한영 혼합 평균
```

위 코드 + spec.py(40) + cost_meter.py(80) + session.py(40) + log_sink.py(50) + errors.py(30) ≈ **~360 LOC core**. 각 provider 모듈을 합쳐도 700 LOC 미만 — 현재 1,200 LOC monolith의 60% 수준.

---

## 10. 마이그레이션 전략 (skeleton sprint 종료 후)

1. **Phase A — 신모듈 추가 only.** `src/runtime/router/`만 생성, 기존 `src/runtime/model-router.py` 그대로. 269 PASS 무조건 유지.
2. **Phase B — adapter shim.** 기존 callers (`council/council-runner.py` 등 25곳)를 위한 `legacy_router_facade.py` 작성. 신 router를 호출하되 구 시그니처를 유지.
3. **Phase C — call site 단계적 이관.** stage 단위로 `ModelRouter().call(...)`로 교체. 25 hot-path 중 가장 단순한 곳부터.
4. **Phase D — old monolith 삭제.** 모든 caller 이관 + 7일 관찰 후.

이 4단계는 worker-1의 API와 worker-3·4의 cost/config 결정이 합쳐진 뒤 별도 PR로 진행한다.

---

## 11. open question (메인 합성 시 결정 필요)

1. **async vs sync default** — worker-1 proposal 결정에 따른다. skeleton은 sync로 시작하지만 `_invoke_with_meter`는 `async def` 변형 추가가 trivial하도록 설계했다.
2. **CostMeter persistence** — 세션 간 누적 추적이 필요한가? skeleton은 process-local. 영속화는 worker-3 + worker-4 결정 후.
3. **prompt/response 본문 저장 위치** — `vault/cost-log.jsonl`은 메타만. 본문 저장은 별도 sink (compliance 분리 위해). 후속 sprint 결정.
4. **stage Literal vs str** — `Stage = Literal["phase0_interview", ...]`로 타입 강제할 것인가, 아니면 `str` + 런타임 검증? 257 PASS 기존 호출자 친화도 vs 타입 안전성.

---

## 12. 요약 — 5줄

- Router는 **얇게**: stage→spec 결정 + fallback loop + cost preflight 만.
- Provider는 **transport-only 함수 한 개**. 회계 안 함.
- CostMeter는 **단일 지점에서 lock**. preflight/commit 두 메서드.
- Log는 **append-only JSONL**, fallback 출처와 session 누적까지 한 줄에.
- Mock provider가 **first-class** 라 269 PASS는 endpoint 없이도 보호된다.
