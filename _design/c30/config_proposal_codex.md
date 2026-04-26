# C30 Model Router Config & Ops Proposal

Worker 4 perspective: make model routing easy to change, safe to operate, and simple to debug across local and cloud endpoints.

## Goals

- Keep stage-to-model decisions in config, not code.
- Allow fast environment overrides without editing repository files.
- Keep secrets outside versioned config.
- Make local/dev operation cheap while preserving production-grade fallback behavior.
- Expose enough observability to explain "why this model was called" and "what did it cost".

## `config/models.json` Schema

The router should load one active profile from `config/models.json`. Each profile defines provider endpoints, named model specs, stage routing, budget policy, health checks, and observability settings.

```json
{
  "schema_version": "1.0",
  "default_profile": "dev",
  "profiles": {
    "dev": {
      "session_budget_usd": 5.0,
      "providers": {
        "anthropic": {
          "type": "anthropic",
          "base_url": "https://api.anthropic.com",
          "api_key_env": "ANTHROPIC_API_KEY",
          "timeout_ms": 60000,
          "rate_limit": { "rpm": 50, "tpm": 100000 }
        },
        "openai": {
          "type": "openai",
          "base_url": "https://api.openai.com/v1",
          "api_key_env": "OPENAI_API_KEY",
          "timeout_ms": 60000,
          "rate_limit": { "rpm": 100, "tpm": 200000 }
        },
        "ollama": {
          "type": "ollama",
          "base_url": "http://localhost:11434",
          "api_key_env": null,
          "timeout_ms": 120000,
          "rate_limit": { "concurrency": 2 }
        },
        "codex_cli": {
          "type": "codex_cli",
          "command": "codex",
          "timeout_ms": 300000
        }
      },
      "models": {
        "sonnet_4_6": {
          "provider": "anthropic",
          "model_id": "claude-sonnet-4-6",
          "context_limit": 200000,
          "max_tokens": 8192,
          "temperature": 0.2,
          "pricing_ref": "anthropic.sonnet_4_6"
        },
        "opus_4_7": {
          "provider": "anthropic",
          "model_id": "claude-opus-4-7",
          "context_limit": 200000,
          "max_tokens": 8192,
          "temperature": 0.2,
          "pricing_ref": "anthropic.opus_4_7",
          "deprecation": {
            "status": "active",
            "replacement": "opus_4_8",
            "effective_after": null
          }
        },
        "gpt_5": {
          "provider": "openai",
          "model_id": "gpt-5",
          "context_limit": 400000,
          "max_tokens": 8192,
          "temperature": 0.2,
          "pricing_ref": "openai.gpt_5"
        },
        "kimi_k2": {
          "provider": "openai",
          "model_id": "kimi-k2",
          "context_limit": 128000,
          "max_tokens": 8192,
          "temperature": 0.2,
          "pricing_ref": "openai_compatible.kimi_k2"
        },
        "qwen3_local": {
          "provider": "ollama",
          "model_id": "qwen3",
          "context_limit": 32768,
          "max_tokens": 4096,
          "temperature": 0.7,
          "pricing_ref": "local.free"
        },
        "deepseek_v4_local": {
          "provider": "ollama",
          "model_id": "deepseek-v4",
          "context_limit": 32768,
          "max_tokens": 4096,
          "temperature": 0.7,
          "pricing_ref": "local.free"
        },
        "codex_review": {
          "provider": "codex_cli",
          "model_id": "codex-default",
          "context_limit": 400000,
          "max_tokens": 8192,
          "temperature": 0.1,
          "pricing_ref": "codex.account"
        }
      },
      "stages": {
        "phase_0_interview": {
          "primary": "sonnet_4_6",
          "fallbacks": ["gpt_5"],
          "required_capabilities": ["interview", "high_reasoning"],
          "budget_policy": "cloud_standard"
        },
        "council_personas_bulk": {
          "primary": "qwen3_local",
          "fallbacks": ["deepseek_v4_local", "sonnet_4_6"],
          "required_capabilities": ["bulk_generation"],
          "budget_policy": "prefer_free"
        },
        "council_rebuttal_verification": {
          "primary": "sonnet_4_6",
          "fallbacks": ["gpt_5"],
          "required_capabilities": ["critique", "verification"],
          "budget_policy": "cloud_standard"
        },
        "eval_11_13_axis": {
          "primary": "sonnet_4_6",
          "fallbacks": ["gpt_5"],
          "required_capabilities": ["evaluation", "structured_output"],
          "budget_policy": "cloud_standard"
        },
        "framework_application": {
          "primary": "sonnet_4_6",
          "fallbacks": ["kimi_k2", "gpt_5"],
          "required_capabilities": ["framework_reasoning"],
          "budget_policy": "cloud_standard"
        },
        "report_composer_mbb_30p": {
          "primary": "opus_4_7",
          "fallbacks": ["gpt_5", "sonnet_4_6"],
          "required_capabilities": ["longform", "executive_synthesis"],
          "budget_policy": "premium_with_cap"
        },
        "code_review": {
          "primary": "codex_review",
          "fallbacks": ["gpt_5"],
          "required_capabilities": ["code_review"],
          "budget_policy": "tool_account"
        },
        "dream_cycle": {
          "primary": "qwen3_local",
          "fallbacks": ["deepseek_v4_local"],
          "required_capabilities": ["divergent_generation"],
          "budget_policy": "local_only"
        }
      },
      "budget_policies": {
        "prefer_free": { "hard_cap_usd": 0.25, "allow_paid_fallback": true },
        "local_only": { "hard_cap_usd": 0.0, "allow_paid_fallback": false },
        "cloud_standard": { "hard_cap_usd": 2.0, "warn_at": [0.5, 0.75, 0.95] },
        "premium_with_cap": { "hard_cap_usd": 4.0, "warn_at": [0.5, 0.75, 0.95] },
        "tool_account": { "hard_cap_usd": 1.0, "warn_at": [0.75, 0.95] }
      },
      "health": {
        "ttl_seconds": 60,
        "startup_probe": true,
        "probe_timeout_ms": 2500
      },
      "observability": {
        "metrics_namespace": "muchanipo.model_router",
        "log_path": "vault/cost-log.jsonl",
        "debug_decision_log": true
      }
    }
  }
}
```

## Override Priority

Use a predictable precedence chain:

1. Built-in defaults in code for schema compatibility only.
2. `config/models.json`.
3. Profile-specific config selected by `MODEL_ROUTER_PROFILE`.
4. Environment variable overrides.
5. CLI flags or explicit constructor arguments.

Recommended env var names:

- `MODEL_ROUTER_PROFILE=dev|staging|prod`
- `MODEL_ROUTER_SESSION_BUDGET_USD=5`
- `MODEL_ROUTER_STAGE__REPORT_COMPOSER_MBB_30P__PRIMARY=gpt_5`
- `MODEL_ROUTER_PROVIDER__OLLAMA__BASE_URL=http://localhost:11434`
- `MODEL_ROUTER_DISABLE_PAID_FALLBACKS=1`
- `MODEL_ROUTER_DEBUG=1`

CLI flags should be reserved for one-off runs and CI:

```bash
muchanipo run --router-profile staging --router-stage report_composer_mbb_30p --router-primary gpt_5
```

## Secrets Management

Versioned config should store only the env var name, never the secret value.

- Local dev: `.env` may be supported but must stay ignored by git.
- CI/staging/prod: inject API keys through the platform secret store.
- Long-lived servers: prefer a secrets manager adapter over reading files.
- Logs must record provider and model IDs but never auth headers, API keys, or raw environment snapshots.

The provider loader should fail fast when a selected cloud provider has no key, unless that provider is only a fallback and a healthy earlier local provider is available.

## Profiles

Profiles should keep operational intent clear:

- `dev`: cheap defaults, local-first bulk stages, verbose decision logging.
- `staging`: production-like model choices, lower session cap, strict health checks.
- `prod`: stable model aliases, explicit paid fallback policy, metrics always on.

Avoid separate config files per profile unless the file becomes too large. A single `models.json` makes diff review easier and prevents hidden divergence.

## Adding a New Model or Provider in Under 5 Minutes

1. Add provider config under `profiles.<profile>.providers` if the provider is new.
2. Add a model entry under `profiles.<profile>.models`.
3. Add or update the stage route under `profiles.<profile>.stages`.
4. Add pricing metadata under the cost registry.
5. Run `model-router doctor --profile <profile>` to validate schema, secrets, health, context limits, and fallback reachability.

The router should support provider plugins through a stable interface:

```text
ProviderClient.call(model_id, prompt, options) -> ProviderResult
ProviderClient.healthcheck() -> HealthStatus
ProviderClient.estimate_tokens(model_id, prompt) -> TokenEstimate
```

New providers should not require changes to stage logic. Stage routing should depend on model keys and capabilities, not provider-specific branches.

## Deprecation Handling

Treat deprecation as a config concern plus a startup validation concern.

- `active`: model is usable.
- `deprecated`: warn on use and prefer configured replacement when `auto_upgrade_deprecated=true`.
- `blocked`: never call; immediately use fallback chain.
- `unknown`: allowed in dev, warning in staging, startup failure in prod.

Example:

```json
{
  "deprecation": {
    "status": "deprecated",
    "replacement": "opus_4_8",
    "effective_after": "2026-09-01",
    "auto_upgrade_profiles": ["dev", "staging"]
  }
}
```

For production, automatic replacement should be opt-in. A silent Opus 4.7 to 4.8 switch can alter tone, cost, latency, and output shape. The router should emit a clear decision log entry whenever it upgrades or skips a deprecated model.

## Observability

Expose metrics that answer operational questions without inspecting raw prompts.

Core metrics:

- `router_calls_total{stage, provider, model, status}`
- `router_tokens_total{stage, provider, model, direction=input|output}`
- `router_cost_usd_total{stage, provider, model}`
- `router_latency_ms{stage, provider, model}` with p50, p90, p99.
- `router_fallback_total{stage, from_model, to_model, reason}`
- `router_budget_remaining_usd{session_id}`
- `router_health_status{provider, model}`
- `router_rate_limit_events_total{provider, model}`

Decision logs should include:

```json
{
  "timestamp": "2026-04-26T00:00:00Z",
  "session_id": "c30-...",
  "stage": "report_composer_mbb_30p",
  "profile": "prod",
  "selected_model": "opus_4_7",
  "fallback_chain": ["gpt_5", "sonnet_4_6"],
  "selection_reason": "stage_primary",
  "budget_policy": "premium_with_cap",
  "estimated_cost_usd": 0.84,
  "actual_cost_usd": 0.79,
  "latency_ms": 42100,
  "status": "success"
}
```

Prompt and response bodies should be excluded by default. If trace capture is needed for debugging, it should require an explicit redaction mode and a short retention period.

## Ops Recommendations

1. Validate config at startup and in CI with a schema checker plus provider health dry-run.
2. Keep stage names stable and treat them as public operational identifiers.
3. Default bulk generation to local models and require explicit config to spend cloud budget on bulk stages.
4. Make fallback reasons typed: `timeout`, `rate_limited`, `provider_down`, `budget_exceeded`, `missing_secret`, `model_deprecated`, `context_exceeded`.
5. Keep a decision log separate from the cost ledger: one explains routing, the other supports accounting.
6. Require an override audit entry whenever CLI flags change a stage primary model.
7. Block production startup when configured fallbacks form a cycle or every model in a stage is unhealthy.
8. Store prices in a dedicated registry with an `effective_date`; model config should reference pricing keys, not duplicate prices.
9. Provide `model-router explain --stage <stage> --profile <profile>` so operators can inspect the selected primary, fallback chain, budget policy, secrets status, and health cache.
10. Prefer explicit profile promotion through reviewed config diffs over ad hoc environment overrides in production.

## Open Design Decisions for Synthesis

- Whether paid fallback from local bulk stages should be allowed by default or require per-run approval.
- Whether `Codex` code review should be modeled as a provider inside the same router or left as a separate tool adapter with only cost/session accounting integration.
- Whether production deprecated-model auto-upgrade should ever be enabled, or only warn and fall back after the model is blocked.
- How much of `vault/cost-log.jsonl` belongs in this repo versus a user-private runtime directory.
