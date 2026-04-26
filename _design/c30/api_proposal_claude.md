# C30 — Model Router API 인터페이스 제안 (Worker 1, claude)

**관점:** Python 사용자가 import 한 줄, 호출 한 줄로 끝나야 한다. 이미 구현된 council/eval/report 코드들이 *최소* 침투로 라우터로 갈아탈 수 있어야 한다.

**원칙 (4개):**
1. **Stage가 1급 시민** — 호출 측은 모델 ID를 모른다. `stage="phase0_interview"` 만 안다.
2. **동기 default + 비동기는 mirror** — council 루프·eval 루프 모두 동기 코드라 sync가 default. async는 `acall` 미러.
3. **에러는 회복 가능 vs 불가능 2층** — fallback chain이 자동으로 회복하다 마지막에 터질 때만 사용자에게 raise.
4. **비용은 호출 객체에 자동 attach** — 사용자가 별도 meter API 호출하지 않아도 router가 session-scoped 누적.

---

## 1. Stage 카탈로그 (enum-like 상수)

호출 측이 오타 못 내게 문자열 상수 모듈로 노출. Worker 4가 정의할 `models.json` key와 1:1 매칭.

```python
# router/stages.py
class Stage:
    PHASE0_INTERVIEW   = "phase0_interview"     # Sonnet 4.6
    COUNCIL_PERSONA    = "council_persona"      # local Qwen3 / DeepSeek V4
    COUNCIL_REBUTTAL   = "council_rebuttal"     # Sonnet 4.6
    EVAL_AXIS          = "eval_axis"            # Sonnet 4.6
    FRAMEWORK_APPLY    = "framework_apply"      # Sonnet 4.6 / Kimi K2
    REPORT_COMPOSER    = "report_composer"      # Opus 4.7 / GPT-5
    CODE_REVIEW        = "code_review"          # Codex
    DREAM_CYCLE        = "dream_cycle"          # local Qwen3
```

이유: stage 이름이 typo면 `KeyError`가 import 시점에 안 나고 호출 시점에 나는데, 상수로 강제하면 IDE/linter가 잡아준다.

---

## 2. `ModelSpec` dataclass

라우터가 stage 해석한 결과. 호출 측은 보통 안 본다 — 디버깅·로깅·테스트용 inspect 인터페이스.

```python
# router/spec.py
from dataclasses import dataclass, field
from typing import Literal, Optional

Provider = Literal["anthropic", "openai", "ollama", "codex_cli", "moonshot", "deepseek"]

@dataclass(frozen=True)
class ModelSpec:
    stage: str                    # "phase0_interview"
    provider: Provider            # "anthropic"
    model_id: str                 # "claude-sonnet-4-6"
    endpoint: Optional[str]       # None이면 SDK default. ollama는 "http://localhost:11434"
    context_limit: int            # 200000 (input+output)
    max_tokens: int               # 8192 (response cap)
    temperature: float            # 0.7
    cost_per_mtok_in: float       # USD per 1M input token, 로컬은 0.0
    cost_per_mtok_out: float      # USD per 1M output token, 로컬은 0.0
    timeout_s: int = 120
    extra: dict = field(default_factory=dict)  # provider-specific (top_p, reasoning_effort 등)
```

`frozen=True` — spec은 불변. config reload 시 router가 새 spec 객체로 통째 교체.

---

## 3. `ModelRouter` 클래스 — 핵심 시그니처

```python
# router/__init__.py
from .spec import ModelSpec
from .stages import Stage
from .errors import (
    RouterError, BudgetExceeded, AllProvidersDown,
    StageNotConfigured, ProviderTimeout, RateLimited,
)

class ModelRouter:
    def __init__(
        self,
        config_path: str = "config/models.json",
        session_id: Optional[str] = None,        # None이면 uuid4
        budget_usd: Optional[float] = 5.0,        # None이면 무제한
        cost_log_path: str = "vault/cost-log.jsonl",
        profile: str = "default",                 # dev/staging/prod
        dry_run: bool = False,                    # True면 호출 대신 spec 반환
    ): ...

    # ── 1) Inspect API (호출 안 함, spec만 본다) ───────────────────────────
    def for_stage(self, stage: str) -> ModelSpec:
        """primary spec 반환. fallback chain은 fallbacks_for(stage)."""

    def fallbacks_for(self, stage: str) -> list[ModelSpec]:
        """primary 실패 시 시도 순서. config의 fallback_chain 그대로."""

    # ── 2) Call API (90% 사용처) ────────────────────────────────────────
    def call(
        self,
        stage: str,
        prompt: str,
        *,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,    # spec default override
        temperature: Optional[float] = None,
        stop: Optional[list[str]] = None,
        metadata: Optional[dict] = None,     # cost-log에 그대로 박힘 (issue id 등)
    ) -> "RouterResponse": ...

    async def acall(self, stage: str, prompt: str, **kw) -> "RouterResponse": ...

    # ── 3) Cost / session API ──────────────────────────────────────────
    @property
    def session_cost_usd(self) -> float: ...
    @property
    def remaining_budget_usd(self) -> Optional[float]: ...
    def reset_session(self, new_id: Optional[str] = None) -> None: ...
```

**`call()`이 `str`이 아니라 `RouterResponse`인 이유:** 사용자는 보통 `.text`만 쓰지만, council 토론 로그·debug에서 `.usage`·`.spec_used`·`.fallback_depth`가 필수. dataclass 한 줄로 wrapping이 깔끔.

```python
@dataclass
class RouterResponse:
    text: str
    spec_used: ModelSpec       # fallback 일어났으면 primary 아닌 spec
    fallback_depth: int        # 0 = primary 성공, 1 = 1차 fallback, ...
    usage: dict                # {"input_tokens":..., "output_tokens":..., "cost_usd":...}
    latency_ms: int
    raw: dict = field(default_factory=dict)  # provider response 원본 (debug용)

    def __str__(self) -> str:  # 가장 흔한 케이스 — print(resp) 그냥 작동
        return self.text
```

`__str__` 덕분에 기존 코드의 `result = client.call(...)` → `result = router.call(stage, ...)` 1줄 교체로 끝남. f-string에 박아도 동작.

---

## 4. 호출 예시 — Phase 0 Interview에서

기존 코드 (예상):
```python
# src/intent/interview_prompts.py — 현재 (가정)
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
msg = client.messages.create(model="claude-sonnet-4-6", max_tokens=8192,
                              messages=[{"role":"user","content":prompt}])
text = msg.content[0].text
```

라우터 적용 후:
```python
# src/intent/interview_prompts.py — after
from router import ModelRouter, Stage

router = ModelRouter(session_id=os.environ.get("MUCHANIPO_SESSION"))

def run_interview(prompt: str) -> str:
    resp = router.call(
        Stage.PHASE0_INTERVIEW, prompt,
        metadata={"phase":"intent", "issue":"#c30"},
    )
    return resp.text   # 또는 그냥 str(resp)
```

Council 대량 페르소나 호출 (다중 stage가 한 함수에 섞임):
```python
# src/council/council-runner.py — after
from router import ModelRouter, Stage
router = ModelRouter()  # 모듈 전역 1개. session_cost가 한 council run에 누적.

def persona_turn(persona: dict, topic: str) -> str:
    return router.call(Stage.COUNCIL_PERSONA,
                       render(persona, topic),
                       temperature=0.9,
                       metadata={"persona": persona["id"]}).text

def rebuttal(prior_turns: list[str]) -> str:
    return router.call(Stage.COUNCIL_REBUTTAL,
                       render_rebuttal(prior_turns),
                       metadata={"role":"rebuttal"}).text

# 한 세션에서 페르소나 50회(local, $0) + 반론 10회(Sonnet) → router.session_cost_usd 자동 누적
```

---

## 5. Sync vs Async — 왜 sync default?

- council-runner / eval / report composer 모두 직렬 의존성 (이전 turn 결과가 다음 prompt). `asyncio.run` 1줄 추가는 호출처 부담.
- 단, **batch 페르소나 50개 동시 호출**처럼 fan-out은 async가 5-10× 빠름. 그래서 `acall`을 1급으로 mirror.
- 내부 구현은 async core + sync는 `asyncio.run` 래핑. 호출 측 부담 없음, 구현 측 코드 1벌.
- 단순 `call`만 쓰면 호출 측은 async 몰라도 됨 — 진입 장벽 0.

---

## 6. 에러 계층

```python
# router/errors.py
class RouterError(Exception):
    """모든 라우터 에러의 base. 외부 코드는 이거만 잡아도 안전."""

class StageNotConfigured(RouterError):
    """models.json에 stage 키 없음. config 문제 — 즉시 raise (no fallback)."""

class BudgetExceeded(RouterError):
    """session_cost + estimated_cost > budget_usd. 호출 직전 차단.
    .session_cost_usd / .budget_usd / .estimated_call_usd 필드 노출."""

class AllProvidersDown(RouterError):
    """primary + fallback chain 모두 실패. .attempts: list[(spec, exc)] 동봉."""

# 내부 회복용 (사용자에게 raise 안 함, 다음 fallback 트리거):
class ProviderTimeout(RouterError): ...
class RateLimited(RouterError):
    retry_after_s: Optional[int]
class ProviderHTTPError(RouterError):
    status: int
```

**설계 결정:** `ProviderTimeout` / `RateLimited`는 router 내부에서 잡고 다음 spec으로 자동 fallback. 사용자에게 보이는 건 `BudgetExceeded` (예방적) / `AllProvidersDown` (체인 소진) / `StageNotConfigured` (config 버그) 3종. 호출 측 try-except가 단순해진다.

```python
try:
    resp = router.call(Stage.REPORT_COMPOSER, prompt)
except BudgetExceeded as e:
    log.warning(f"session cost {e.session_cost_usd:.2f} hit cap {e.budget_usd}; degrading to summary")
    resp = router.call(Stage.EVAL_AXIS, summary_prompt)  # 더 싼 stage로 의식적 강등
except AllProvidersDown as e:
    log.error(f"all {len(e.attempts)} providers failed: {e.attempts}")
    raise
```

---

## 7. 합쳐 pseudo-code (≈70 LOC)

```python
# router/__init__.py — 핵심만
import json, time, uuid, asyncio
from .spec import ModelSpec
from .errors import *
from .providers import get_provider           # registry: provider name → call fn
from .cost_meter import CostMeter             # worker 2/3가 채움
from .config_loader import load_specs         # worker 4가 채움

class ModelRouter:
    def __init__(self, config_path="config/models.json", session_id=None,
                 budget_usd=5.0, cost_log_path="vault/cost-log.jsonl",
                 profile="default", dry_run=False):
        self._specs: dict[str, list[ModelSpec]] = load_specs(config_path, profile)
        self.session_id = session_id or str(uuid.uuid4())
        self.budget_usd = budget_usd
        self._meter = CostMeter(self.session_id, cost_log_path)
        self.dry_run = dry_run

    def for_stage(self, stage: str) -> ModelSpec:
        chain = self._specs.get(stage)
        if not chain: raise StageNotConfigured(stage)
        return chain[0]

    def fallbacks_for(self, stage: str) -> list[ModelSpec]:
        return self._specs.get(stage, [])[1:]

    @property
    def session_cost_usd(self) -> float: return self._meter.total_usd
    @property
    def remaining_budget_usd(self):
        return None if self.budget_usd is None else self.budget_usd - self._meter.total_usd

    def call(self, stage, prompt, **kw) -> RouterResponse:
        return asyncio.run(self.acall(stage, prompt, **kw))

    async def acall(self, stage, prompt, *, system=None, max_tokens=None,
                    temperature=None, stop=None, metadata=None) -> RouterResponse:
        chain = self._specs.get(stage)
        if not chain: raise StageNotConfigured(stage)

        # budget pre-check (estimate by char/4 heuristic; worker 3가 정밀화)
        est = self._meter.estimate(chain[0], prompt, max_tokens or chain[0].max_tokens)
        if self.budget_usd is not None and self._meter.total_usd + est > self.budget_usd:
            raise BudgetExceeded(self._meter.total_usd, self.budget_usd, est)

        attempts = []
        for depth, spec in enumerate(chain):
            if self.dry_run:
                return RouterResponse(text="[dry_run]", spec_used=spec, fallback_depth=depth,
                                      usage={"cost_usd":0}, latency_ms=0)
            try:
                t0 = time.monotonic()
                provider = get_provider(spec.provider)
                text, usage = await provider(spec, prompt, system=system,
                                             max_tokens=max_tokens or spec.max_tokens,
                                             temperature=temperature if temperature is not None else spec.temperature,
                                             stop=stop)
                latency = int((time.monotonic() - t0) * 1000)
                cost = self._meter.record(spec, usage, stage=stage, metadata=metadata)
                return RouterResponse(text=text, spec_used=spec, fallback_depth=depth,
                                      usage={**usage, "cost_usd": cost},
                                      latency_ms=latency)
            except (ProviderTimeout, RateLimited, ProviderHTTPError) as e:
                attempts.append((spec, e))
                continue                              # 다음 fallback
        raise AllProvidersDown(stage, attempts)
```

---

## 8. 토론 포인트 (다른 worker에게 떠넘기는 결정)

- **W2 (impl):** `get_provider(name)`는 import-time registry 인가, lazy lookup 인가? lazy면 `providers/anthropic.py`가 `anthropic` SDK 미설치여도 router import는 성공.
- **W3 (cost):** `self._meter.estimate()`의 prompt → input_tokens 휴리스틱. `len(prompt)//4`로 시작하되 provider별 tokenizer 정확화는 W3 책임.
- **W3 (cost):** budget pre-check vs post-check — 위 pseudo는 estimate 기반 pre-check만. post-check (실제 cost 누적이 cap 넘으면 *다음 호출* 차단)도 필요한지?
- **W4 (config):** `_specs[stage]`가 list — primary가 index 0, fallback 1..N. config 스키마 그대로 따름. profile 분기는 `load_specs(profile=...)`가 흡수.
- **W4 (config):** `endpoint`가 spec에 들어가는 게 맞나? Ollama는 endpoint, Anthropic은 SDK default URL — provider 모듈에서 `spec.endpoint or DEFAULT_URL` 패턴.

---

## 9. 명시적 비결정 (구현 sprint에서 정함)

- streaming API (`stream=True`) — v1 미포함. report composer 30p가 길어서 v2에서 `astream(stage, prompt) -> AsyncIterator[str]` 추가 검토.
- multi-modal (이미지 입력) — v1 미포함. Phase 0 interview에 첨부 들어오면 그때.
- structured output (`response_format={"type":"json_schema",...}`) — v1 미포함. Eval 11/13 axis가 JSON 강제하면 그때 `call(..., schema=...)` 추가.
- caching (Anthropic prompt cache) — `extra={"cache_control":...}` 로 우회 가능, 1급 API화는 v2.

---

## 10. 요약 — 호출 측이 외울 것

```python
from router import ModelRouter, Stage
router = ModelRouter()                     # 1) 모듈 전역 1개
resp = router.call(Stage.X, prompt)        # 2) stage 상수 + prompt
print(resp.text, resp.spec_used.model_id)  # 3) 결과 + 어느 모델 썼는지
print(router.session_cost_usd)             # 4) 세션 누적 비용
```

이 4줄이 router API의 전부. 나머지는 inspect/error/async mirror 부속.
