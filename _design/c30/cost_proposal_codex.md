# C30 Model Router Cost and Fallback Proposal

Worker: worker-3
Scope: Cost accounting correctness, fallback policy, concurrency safety, and edge cases.
Constraint: Design only. No implementation changes in this sprint.

## Position

The router should treat cost tracking as a first-class control plane, not as a log-only side effect. Every model call needs a stable ledger record, a deterministic budget decision, and an explicit fallback reason. Without that, session caps will be approximate, concurrent calls can overspend, and fallback behavior will become hard to debug.

Recommended principle:

1. Estimate before the call.
2. Reserve budget atomically before dispatch.
3. Reconcile with provider usage after the call.
4. Log both estimate and actual usage.
5. Make fallback decisions from typed failure reasons, not from generic exceptions.

## Token Counting Strategy

Different providers expose different tokenizers and sometimes different usage fields. The router should normalize to a common accounting record while preserving provider-native details.

### Canonical Units

Use these canonical fields for every call:

```json
{
  "session_id": "20260426-c30",
  "stage": "phase0_interview",
  "provider": "anthropic",
  "model_id": "sonnet-4.6",
  "attempt": 1,
  "status": "success",
  "input_tokens_estimated": 1820,
  "output_tokens_estimated": 900,
  "input_tokens_actual": 1764,
  "output_tokens_actual": 811,
  "cache_read_tokens": 0,
  "cache_write_tokens": 0,
  "batch_multiplier": 1.0,
  "estimated_cost_usd": 0.0127,
  "actual_cost_usd": 0.0119,
  "budget_reserved_usd": 0.0150,
  "fallback_reason": null,
  "latency_ms": 8342,
  "created_at": "2026-04-26T00:00:00Z"
}
```

### Provider-Specific Tokenizer Policy

Use provider-native usage when available:

| Provider | Primary source | Preflight estimate | Notes |
| --- | --- | --- | --- |
| Anthropic | response `usage` | Anthropic tokenizer API if available, otherwise calibrated char ratio | Preserve cache creation/read tokens separately. |
| OpenAI / GPT | response `usage` | `tiktoken` only if already present; otherwise calibrated char ratio | Do not add a dependency in this sprint. |
| Local Llama / Ollama | response eval counts when available | model-family calibrated char ratio | Treat local cost as zero dollars but still count tokens and latency. |
| Codex CLI | structured output if available; otherwise estimate | calibrated char ratio | Mark actual usage confidence as low when CLI does not expose usage. |
| Kimi / DeepSeek | response usage if available | provider docs/tokenizer if available; fallback estimate | Keep price table model-versioned. |

If no tokenizer is available, estimate conservatively:

```text
estimated_input_tokens = ceil(input_chars / ratio_chars_per_token * safety_factor)
estimated_output_tokens = requested_max_tokens
```

Recommended defaults:

| Model family | chars/token ratio | safety factor |
| --- | ---: | ---: |
| English-heavy GPT/Claude | 4.0 | 1.15 |
| Korean-heavy GPT/Claude | 2.2 | 1.20 |
| Mixed Korean/English | 3.0 | 1.20 |
| Code-heavy | 3.2 | 1.15 |
| Unknown local model | 3.0 | 1.30 |

The router should store `usage_confidence` as `actual`, `provider_reported_partial`, `estimated`, or `missing`. This prevents later analytics from treating estimates as exact facts.

## Cost Formula

Price tables should be versioned by provider and model id:

```json
{
  "provider": "anthropic",
  "model_id": "sonnet-4.6",
  "effective_from": "2026-04-01",
  "input_usd_per_million": 3.00,
  "output_usd_per_million": 15.00,
  "cache_write_usd_per_million": 3.75,
  "cache_read_usd_per_million": 0.30,
  "batch_multiplier": 0.50
}
```

Canonical formula:

```text
base_cost =
  input_tokens * input_price_per_token
  + output_tokens * output_price_per_token
  + cache_write_tokens * cache_write_price_per_token
  + cache_read_tokens * cache_read_price_per_token

actual_cost = base_cost * batch_multiplier
```

Rules:

1. Use integer token counts and decimal arithmetic for money.
2. Store costs in micros or Decimal strings, not binary floats.
3. Price lookup must include provider, model id, and effective date.
4. If price is unknown, fail closed for paid providers unless the caller explicitly allows `unknown_cost_policy=estimate`.
5. Local models should log `actual_cost_usd=0` and `compute_cost_class=local_unpriced`, not omit cost fields.

## Session Cap Design

Session caps need both a soft warning system and a hard stop.

Recommended thresholds for a default `$5/session` cap:

| Threshold | Action |
| --- | --- |
| 50% | Emit warning event; continue. |
| 75% | Prefer free/local fallbacks for low-criticality stages. |
| 95% | Require explicit high-value stage override or route to local only. |
| 100% | Hard stop for paid providers. |

Cap policy should be stage-aware:

| Stage class | Below 75% | 75-95% | Above 95% |
| --- | --- | --- | --- |
| Interview / clarification | Sonnet primary | Sonnet allowed if short | Stop paid unless user override |
| Bulk council personas | Local primary | Local only | Local only |
| Council critique / eval | Sonnet primary | Sonnet with max token clamp | Stop paid or defer |
| Report composer | Opus/GPT-5 allowed | Kimi/Sonnet if cheaper | Pause before paid call |
| Code review | Codex | Codex if subscription/no marginal cost | Pause if metered |
| Dream cycle | Local | Local | Local |

Budget checks should use preflight reservation:

```text
if spent + reserved + estimate > cap:
    reject paid attempt before dispatch
else:
    reserve estimate
    dispatch
    reconcile reserve against actual usage
```

This avoids a race where several concurrent calls each see available budget and collectively overspend the cap.

## Concurrency and Race Conditions

The cost meter must be safe under concurrent calls from council fan-out.

Recommended minimal design:

1. One session ledger file: `vault/cost-log.jsonl`.
2. One session aggregate file: `vault/cost-session-{session_id}.json`.
3. Per-session lock around aggregate read, reserve, write, and reconcile.
4. Append-only JSONL for audit; aggregate file is a cache that can be rebuilt.

Atomicity requirements:

```text
with session_lock(session_id):
    aggregate = read_aggregate()
    if aggregate.spent + aggregate.reserved + estimate > cap:
        raise BudgetExceeded
    reservation_id = uuid4()
    aggregate.reserved += estimate
    write_aggregate_atomically()

try:
    result = provider.call(...)
finally:
    with session_lock(session_id):
        aggregate.reserved -= reserved_amount
        aggregate.spent += actual_or_estimated_cost
        append_ledger_event()
        write_aggregate_atomically()
```

Use an atomic rename for aggregate writes. If file locking is not portable enough, move the aggregate into SQLite later; the public `CostMeter` API should not expose the storage choice.

Important edge cases:

1. Provider call succeeds but process dies before reconcile: a startup repair job should convert stale reservations older than TTL into `orphaned_reservation` ledger events.
2. Provider times out but later completes server-side: cost may be unknown; log max reserved estimate until usage can be reconciled.
3. Streaming response is interrupted: charge actual tokens if provider reports them; otherwise charge estimated output tokens generated so far if known.
4. Fallback attempt after failure: charge each paid attempt independently. Failed attempts can still cost money.
5. Retried idempotent request: use `request_id` and `attempt` to avoid double-counting the same provider response.

## Fallback Trigger Policy

Fallback should be driven by typed reasons. A single fallback chain is not enough because rate limits, outages, quality policy, and budget pressure should choose different routes.

Recommended failure taxonomy:

| Reason | Examples | Retry same provider? | Fallback target |
| --- | --- | --- | --- |
| `timeout` | request exceeded stage timeout | once if idempotent and cheap | faster cloud or local summary mode |
| `rate_limited` | HTTP 429 | after `retry-after` if within SLA | alternate paid provider or local |
| `auth_failed` | missing/expired API key | no | local or configured alternate |
| `provider_down` | connection refused, 5xx burst | no until health TTL expires | next provider |
| `budget_soft_limit` | 75% or 95% threshold | no | cheaper/local route |
| `budget_hard_limit` | cap exceeded | no paid fallback | local only or raise |
| `context_overflow` | prompt exceeds context | no immediate retry | larger context model or chunking |
| `safety_block` | provider refuses | no blind retry | policy-specific escalation |
| `quality_guard_failed` | validator rejects answer | yes with repair prompt | stronger model |

Fallback chains should be per stage and per reason:

```json
{
  "stage": "council_persona_bulk",
  "primary": "ollama:qwen3",
  "fallbacks": {
    "provider_down": ["ollama:deepseek-v4", "anthropic:sonnet-4.6"],
    "budget_soft_limit": ["ollama:qwen3"],
    "quality_guard_failed": ["anthropic:sonnet-4.6"],
    "context_overflow": ["kimi:k2"]
  }
}
```

For the user-required target routing:

| Stage | Primary | Cost/fallback rule |
| --- | --- | --- |
| Phase 0 Interview | Sonnet 4.6 | Stop or ask for override at hard cap; do not silently degrade to local. |
| Council personas bulk | Local Qwen3 / DeepSeek V4 | If local down, use cloud only while below 75% cap or if explicitly marked urgent. |
| Council critique | Sonnet 4.6 | On 429, fallback to GPT-5 or Kimi if quality acceptable; on cap, pause. |
| Eval 11/13 axis | Sonnet 4.6 | Keep max tokens tight; fallback to local only for draft scoring, not final scoring. |
| Framework apply | Sonnet 4.6 or Kimi K2 | Context overflow should prefer Kimi before chunking. |
| Report composer | Opus 4.7 or GPT-5 | Do not start if estimate would cross 95% without override. |
| Code review | Codex | If CLI unavailable, fail clearly instead of substituting a chat model silently. |
| Dream cycle | Local Qwen3 | No paid fallback by default. |

## Health Checks

Health should be cached to avoid probing every call.

Recommended TTLs:

| Provider class | Check | TTL |
| --- | --- | --- |
| Ollama/local | `/api/tags`, model present | 30 seconds |
| API key provider | env/key present plus lightweight models endpoint if cheap | 5 minutes |
| CLI provider | `codex --version` or equivalent | 5 minutes |
| Provider after 429 | honor `retry-after` | retry-after plus jitter |
| Provider after auth failure | cache unhealthy until env changes or 10 minutes | 10 minutes |

Do not run expensive generation calls as health checks. A provider can be "transport healthy" while a specific model is unavailable; keep `provider_health` and `model_health` separate.

Health record shape:

```json
{
  "provider": "ollama",
  "model_id": "qwen3",
  "transport_ok": true,
  "model_ok": false,
  "checked_at": "2026-04-26T00:00:00Z",
  "ttl_seconds": 30,
  "failure_reason": "model_missing"
}
```

## Missing Usage Fields

When provider usage is absent:

1. Mark `usage_confidence=estimated`.
2. Charge the session against the conservative estimate.
3. Preserve raw provider metadata for later audit.
4. Emit `usage_missing` metric by provider/model.
5. Never retroactively lower the cap decision during the same call. Reconciliation can reduce aggregate spent after the fact, but preflight must remain conservative.

For streaming:

1. Count prompt estimate before dispatch.
2. Count streamed output chunks with the best available tokenizer estimate.
3. Reconcile with provider final usage if present.
4. If final usage is missing, use the streamed estimate plus safety factor.

## Budget Policy API

The router should expose budget decisions as explicit objects:

```python
BudgetDecision(
    allowed=True,
    reason="below_cap",
    cap_usd=Decimal("5.00"),
    spent_usd=Decimal("1.72"),
    reserved_usd=Decimal("0.20"),
    estimate_usd=Decimal("0.08"),
    threshold="normal",
)
```

For denied calls:

```python
BudgetDecision(
    allowed=False,
    reason="hard_cap_exceeded",
    recommended_fallbacks=["ollama:qwen3", "ollama:deepseek-v4"],
)
```

This makes CLI output and tests deterministic.

## Logging and Audit

Every attempt should append one ledger event. Required event types:

1. `reservation_created`
2. `provider_attempt_started`
3. `provider_attempt_succeeded`
4. `provider_attempt_failed`
5. `reservation_reconciled`
6. `fallback_selected`
7. `budget_warning`
8. `budget_denied`
9. `orphaned_reservation_repaired`

The human-readable run summary should answer:

1. Which stages spent the most?
2. Which providers triggered fallback?
3. How much was estimated vs actual?
4. How much paid usage was avoided by local routing?
5. Did any calls proceed with unknown prices or estimated usage?

## Test Strategy

Even though this sprint is design-only, the eventual implementation should be tested without real endpoints.

Core tests:

1. Price calculation with input, output, cache read/write, and batch multiplier.
2. Unknown price fails closed for paid providers.
3. 50%, 75%, 95%, and 100% threshold behavior.
4. Concurrent reservations cannot exceed cap.
5. Failed paid attempts are still charged when usage is known.
6. Missing provider usage falls back to conservative estimate.
7. 429 uses rate-limit fallback chain, not outage chain.
8. Ollama down routes to cloud only when stage policy permits.
9. Hard cap blocks paid fallback but allows local fallback.
10. Stale reservation repair does not double-charge.

Use a mock provider that returns scripted success, failure, delay, and usage payloads.

## Recommendations

1. Make budget reservation mandatory for every paid provider call.
2. Separate routing fallback reasons from provider exception classes.
3. Store estimates and actuals side by side; never overwrite estimates.
4. Use Decimal or integer micros for money.
5. Treat local models as zero-dollar but not zero-accounting.
6. Fail closed when paid model prices are unknown.
7. Define per-stage fallback chains by failure reason.
8. Cache health checks with short TTLs and distinguish provider health from model health.
9. Emit warning events at 50%, 75%, and 95%, but enforce a hard stop at 100%.
10. Keep the append-only ledger authoritative and rebuild aggregates from it when needed.

## Integration Contract for the Final Design

Worker 3 recommends these interfaces for the combined design:

```python
class CostMeter:
    def estimate(stage, model_spec, prompt, max_tokens) -> CostEstimate: ...
    def reserve(session_id, estimate) -> Reservation: ...
    def reconcile(reservation, usage, status) -> CostRecord: ...

class FallbackPolicy:
    def classify_error(exc_or_response) -> FailureReason: ...
    def candidates(stage, reason, budget_decision, health) -> list[ModelSpec]: ...
```

The router should call these before and after provider dispatch:

```text
route stage -> estimate cost -> reserve budget -> attempt provider
  -> classify result -> reconcile cost -> maybe fallback by reason
```

This keeps the core router simple while making the cost and fallback behavior testable.
