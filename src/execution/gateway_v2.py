"""Model Gateway v2 — PRD §8.1 stage routing + multi-step fallback chain.

Stage routing per PRD-v2 §8.1 (Qwen 보류):
    Intake     → Gemini (Flash)
    Interview  → Anthropic Sonnet
    Targeting  → Gemini
    Research   → Gemini + Kimi + OpenCode (parallel — chosen by caller)
    Evidence   → Kimi
    Council    → Anthropic Opus
    Report     → Anthropic Sonnet  (Qwen 로컬 보류)
    Eval       → Codex (GPT-5.4)

Fallback chain per stage — first failure → next provider in chain.
The app path is CLI-first: installed Claude/Gemini/Kimi/Codex CLIs own their
own auth, and API keys are only fallback inputs. Providers return
deterministic mocks when neither CLI nor API credentials are available.

stdlib only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence

from src.execution.models import ModelGateway, ModelResult, Provider
from src.governance.budget import BudgetExceeded, provider_name, resolve_model
from src.runtime.live_mode import (
    LiveModeViolation,
    assert_live_model_result,
    live_requested_from_env,
    mimo_opencode_only_requested_from_env,
)


# ---- Stage → primary provider name (PRD-v2 §8.1) -------------------------

PRIMARY_ROUTES: Dict[str, str] = {
    "intake":    "gemini",
    "interview": "anthropic",
    "targeting": "gemini",
    "research":  "gemini",
    "evidence":  "kimi",
    "council":   "anthropic",
    "report":    "anthropic",
    "eval":      "codex",
    "utilities": "opencode",
    "implementation_review": "opencode",
    # Convenience aliases used elsewhere
    "consensus": "anthropic",
    "ingest":    "gemini",
}


# Per-stage fallback chain — provider names tried in order on failure.
FALLBACK_CHAIN: Dict[str, List[str]] = {
    "intake":    ["gemini", "anthropic", "mock"],
    "interview": ["anthropic", "gemini", "mock"],
    "targeting": ["gemini", "anthropic", "mock"],
    "research":  ["gemini", "kimi", "opencode", "anthropic", "mock"],
    "evidence":  ["kimi", "gemini", "opencode", "anthropic", "mock"],
    "council":   ["anthropic", "codex", "kimi", "gemini", "opencode", "mock"],
    "report":    ["anthropic", "gemini", "opencode", "mock"],
    "eval":      ["codex", "opencode", "anthropic", "mock"],
    "consensus": ["anthropic", "gemini", "mock"],
    "ingest":    ["gemini", "anthropic", "mock"],
    "utilities": ["opencode", "codex", "mock"],
    "implementation_review": ["opencode", "codex", "anthropic", "mock"],
}


# ---- Multi-step fallback wrapper -----------------------------------------


@dataclass
class FallbackChain:
    """Provider 시퀀스를 try-next 패턴으로 호출한다.

    예: FallbackChain([primary, secondary, tertiary]).call(stage, prompt)
        primary 실패 → secondary → tertiary → 마지막 실패 시 raise
    """

    name: str
    providers: List[Provider]
    on_fallback: Optional[Any] = None  # callback(stage, failed_provider, error)

    def call(self, stage: str, prompt: str, **kwargs: Any) -> ModelResult:
        last_error: Optional[Exception] = None
        for i, provider in enumerate(self.providers):
            try:
                result = provider.call(
                    stage=stage,
                    prompt=prompt,
                    **_chain_call_kwargs(provider, kwargs),
                )
                if i > 0:
                    result.is_fallback = True
                    result.fallback_reason = (
                        f"primary {self.providers[0].name} failed: {last_error}"
                    )
                return result
            except Exception as exc:
                last_error = exc
                if self.on_fallback:
                    try:
                        self.on_fallback(stage, provider, exc)
                    except Exception:  # pragma: no cover - 콜백 장애 무시
                        pass
                continue
        raise RuntimeError(
            f"FallbackChain {self.name} exhausted ({len(self.providers)} providers) — last: {last_error}"
        ) from last_error


# ---- Default factory ------------------------------------------------------


def build_default_providers(
    *,
    force_offline: bool = False,
    prefer_cli: bool = True,
) -> Dict[str, Provider]:
    """기본 provider 세트 (anthropic/gemini/kimi/codex/opencode/mock).

    force_offline=True면 모든 LLM provider를 offline 모드로 강제 — 테스트용.
    """
    from src.execution.providers.anthropic import AnthropicProvider
    from src.execution.providers.codex import CodexProvider
    from src.execution.providers.gemini import GeminiProvider
    from src.execution.providers.kimi import KimiProvider
    from src.execution.providers.mimo import MiMoProvider
    from src.execution.providers.mock import MockProvider
    from src.execution.providers.opencode import OpenCodeProvider

    providers: Dict[str, Provider] = {
        "mimo": MiMoProvider(offline=True if force_offline else None, prefer_cli=prefer_cli),
        "anthropic": AnthropicProvider(offline=True if force_offline else None, prefer_cli=prefer_cli),
        "gemini": GeminiProvider(offline=True if force_offline else None, prefer_cli=prefer_cli),
        "kimi": KimiProvider(offline=True if force_offline else None, prefer_cli=prefer_cli),
        "codex": CodexProvider(offline=True if force_offline else None, prefer_cli=prefer_cli),
        "opencode": OpenCodeProvider(offline=True if force_offline else None, prefer_cli=prefer_cli),
        "mock": MockProvider(),
    }
    return providers


def _mimo_available(providers: Mapping[str, Provider]) -> bool:
    provider = providers.get("mimo")
    return provider is not None and not bool(getattr(provider, "offline", False))


def _with_mimo_primary_routes(routes: Mapping[str, str]) -> Dict[str, str]:
    updated = dict(routes)
    for stage in (
        "intake",
        "interview",
        "targeting",
        "research",
        "evidence",
        "council",
        "report",
        "eval",
        "consensus",
        "ingest",
    ):
        updated[stage] = "mimo"
    return updated


def _with_mimo_first_chain(fallback_chain: Mapping[str, Sequence[str]]) -> Dict[str, List[str]]:
    updated: Dict[str, List[str]] = {}
    for stage, names in fallback_chain.items():
        chain = [name for name in names if name != "mimo"]
        if stage not in ("utilities", "implementation_review"):
            chain.insert(0, "mimo")
        updated[stage] = chain
    return updated


def _mimo_opencode_only_requested() -> bool:
    return mimo_opencode_only_requested_from_env()


def _requested_provider_chain() -> List[str]:
    raw = os.environ.get("MUCHANIPO_PROVIDER_CHAIN", "")
    return [part.strip().lower() for part in raw.split(",") if part.strip()]


def _with_mimo_opencode_only_routes(routes: Mapping[str, str]) -> Dict[str, str]:
    requested_chain = _requested_provider_chain()
    opencode_only = requested_chain == ["opencode"]
    updated = dict(routes)
    for stage in tuple(updated):
        if opencode_only:
            updated[stage] = "opencode"
        else:
            updated[stage] = "opencode" if stage in {"utilities", "implementation_review"} else "mimo"
    return updated


def _with_mimo_opencode_only_chain(fallback_chain: Mapping[str, Sequence[str]]) -> Dict[str, List[str]]:
    requested_chain = _requested_provider_chain()
    opencode_only = requested_chain == ["opencode"]
    updated: Dict[str, List[str]] = {}
    for stage in fallback_chain:
        if opencode_only:
            updated[stage] = ["opencode"]
        else:
            updated[stage] = ["opencode"] if stage in {"utilities", "implementation_review"} else ["mimo", "opencode"]
    return updated


def default_gateway(
    *,
    providers: Optional[Mapping[str, Provider]] = None,
    routes: Optional[Mapping[str, str]] = None,
    fallback_chain: Optional[Mapping[str, Sequence[str]]] = None,
    budget: Any = None,
    audit: Any = None,
    force_offline: bool = False,
    require_live_default: bool = False,
    prefer_cli: bool = True,
) -> "GatewayV2":
    """PRD §8.1 기본 라우팅 + fallback chain을 갖춘 GatewayV2 인스턴스."""
    provider_map = dict(providers) if providers else build_default_providers(
        force_offline=force_offline,
        prefer_cli=prefer_cli,
    )
    stage_routes = dict(routes or PRIMARY_ROUTES)
    chain = {k: list(v) for k, v in dict(fallback_chain or FALLBACK_CHAIN).items()}
    if _mimo_opencode_only_requested():
        stage_routes = _with_mimo_opencode_only_routes(stage_routes)
        chain = _with_mimo_opencode_only_chain(chain)
    elif _mimo_available(provider_map) and routes is None and fallback_chain is None:
        stage_routes = _with_mimo_primary_routes(stage_routes)
        chain = _with_mimo_first_chain(chain)
    return GatewayV2(
        providers=provider_map,
        stage_routes=stage_routes,
        fallback_chain=chain,
        budget=budget,
        audit=audit,
        require_live_default=require_live_default,
    )


# ---- GatewayV2 — extends ModelGateway with multi-step fallback ----------


class GatewayV2(ModelGateway):
    """ModelGateway 확장 — stage별 fallback 체인 지원.

    기존 ModelGateway는 단일 fallback_provider만 지원. v2는
    `fallback_chain[stage]` 시퀀스를 따라 순차 시도.
    """

    def __init__(
        self,
        *,
        providers: Mapping[str, Provider],
        stage_routes: Mapping[str, str],
        fallback_chain: Mapping[str, Sequence[str]],
        budget: Any = None,
        audit: Any = None,
        require_live_default: bool = False,
    ) -> None:
        # 기본 ModelGateway 초기화 (fallback_provider는 미사용 — 체인이 대신함)
        super().__init__(
            providers=providers,
            stage_routes=stage_routes,
            budget=budget,
            audit=audit,
        )
        self.fallback_chain: Dict[str, List[str]] = {
            k: list(v) for k, v in fallback_chain.items()
        }
        self._fallback_events: List[Dict[str, Any]] = []
        self.require_live_default = bool(require_live_default)
        self._dead_providers: set[str] = set()

    def call(self, stage: str, prompt: str, **kwargs: Any) -> ModelResult:
        require_live = (
            bool(kwargs.pop("require_live", False))
            or self.require_live_default
            or live_requested_from_env()
        )
        chain_names = self.fallback_chain.get(stage)
        if require_live and chain_names:
            chain_names = self._live_chain_names(stage, chain_names)
        if not chain_names:
            # 체인 미정의 → 기본 ModelGateway 동작
            result = super().call(stage, prompt, **kwargs)
            if require_live:
                assert_live_model_result(stage, result)
            return result

        chain_providers: List[Provider] = []
        for name in chain_names:
            if name in self._dead_providers:
                continue
            prov = self.providers.get(name)
            if prov is not None:
                chain_providers.append(prov)
        if not chain_providers:
            dead_detail = f" (dead: {', '.join(sorted(self._dead_providers))})" if self._dead_providers else ""
            raise KeyError(
                f"stage {stage!r} fallback chain has no resolvable providers{dead_detail}"
            )

        reservation_id = None
        primary = chain_providers[0]
        if self.budget is not None:
            last_error: Exception | None = None
            first_fallback_reason: str | None = None
            for i, provider in enumerate(chain_providers):
                estimated_usd = self.budget.estimate(stage=stage, prompt=prompt, provider=provider)
                reservation_id = self.budget.reserve(
                    stage=stage,
                    estimated_usd=estimated_usd,
                    provider=provider_name(provider),
                    model=resolve_model(stage=stage, provider=provider),
                )
                if reservation_id is False:
                    error = BudgetExceeded("budget exceeded")
                    self._record_fallback(stage, provider, error)
                    last_error = error
                    if first_fallback_reason is None:
                        first_fallback_reason = f"primary {primary.name} failed: budget exceeded"
                    continue
                try:
                    result = self.dispatch(
                        provider,
                        stage=stage,
                        prompt=prompt,
                        **_chain_call_kwargs(provider, kwargs),
                    )
                except Exception as exc:
                    last_error = exc
                    self.budget.reconcile(reservation_id, actual_usd=0.0)
                    self._record_fallback(stage, provider, exc)
                    # Only mark dead when alternatives exist; single-provider
                    # chains should keep failing with the original error.
                    if self._is_auth_error(exc) and len(chain_providers) > 1:
                        self._mark_provider_dead(provider_name(provider), exc)
                    if first_fallback_reason is None:
                        first_fallback_reason = f"primary {primary.name} failed: {exc}"
                    continue

                if i > 0 or provider is not primary:
                    result.is_fallback = True
                    result.fallback_reason = first_fallback_reason
                actual_usd = float(getattr(result, "cost_usd", 0.0) or 0.0)
                self.budget.reconcile(reservation_id, actual_usd=actual_usd)
                actual_provider = self._provider_from_result(result, provider)
                self._audit(stage, actual_provider, result, actual_usd, result.fallback_reason)
                if require_live:
                    assert_live_model_result(stage, result)
                return result
            raise RuntimeError(
                f"FallbackChain {stage} exhausted ({len(chain_providers)} providers) — last: {last_error}"
            ) from last_error

        chain = FallbackChain(
            name=stage,
            providers=chain_providers,
            on_fallback=self._record_fallback,
        )
        try:
            result = chain.call(stage=stage, prompt=prompt, **kwargs)
        except Exception:
            if reservation_id and self.budget is not None:
                self.budget.reconcile(reservation_id, actual_usd=0.0)
            # Mark providers dead from fallback events even in the no-budget path,
            # but only when alternatives exist.
            if len(chain_providers) > 1:
                self._mark_auth_failures_from_events(stage)
            raise
        if len(chain_providers) > 1:
            self._mark_auth_failures_from_events(stage)

        actual_usd = float(getattr(result, "cost_usd", 0.0) or 0.0)
        if reservation_id and self.budget is not None:
            self.budget.reconcile(reservation_id, actual_usd=actual_usd)
        actual_provider = self._provider_from_result(result, primary)
        self._audit(stage, actual_provider, result, actual_usd, result.fallback_reason)
        if require_live:
            assert_live_model_result(stage, result)
        return result

    def _record_fallback(self, stage: str, provider: Provider, error: Exception) -> None:
        self._fallback_events.append({
            "stage": stage,
            "provider": getattr(provider, "name", str(provider)),
            "error": str(error),
        })

    def _live_chain_names(self, stage: str, chain_names: Sequence[str]) -> List[str]:
        live_names: List[str] = []
        skipped: List[str] = []
        for name in chain_names:
            provider = self.providers.get(name)
            if provider is None:
                skipped.append(f"{name}:missing")
                continue
            if _is_live_provider_candidate(provider):
                live_names.append(name)
            else:
                skipped.append(f"{name}:mock_or_offline")
        if not live_names:
            detail = ", ".join(skipped) if skipped else "empty chain"
            raise LiveModeViolation(
                f"live mode has no live provider candidates for stage {stage!r}: {detail}"
            )
        return live_names

    def assert_live_provider_candidates(self, stages: Sequence[str]) -> Dict[str, List[str]]:
        """Fail before pipeline work starts if any live stage can only route to mock/offline providers."""
        status: Dict[str, List[str]] = {}
        missing: List[str] = []
        for stage in stages:
            chain_names = self.fallback_chain.get(stage)
            if not chain_names:
                route = self.stage_routes.get(stage)
                chain_names = [route] if route else []
            try:
                status[stage] = self._live_chain_names(stage, chain_names)
            except LiveModeViolation as exc:
                missing.append(str(exc))
        if missing:
            raise LiveModeViolation("; ".join(missing))
        return status

    def _provider_from_result(self, result: ModelResult, default: Provider) -> Provider:
        provider_name = getattr(result, "provider", None)
        if isinstance(provider_name, str):
            return self.providers.get(provider_name, default)
        return default

    @property
    def fallback_events(self) -> List[Dict[str, Any]]:
        return list(self._fallback_events)

    @staticmethod
    def _is_auth_error(exc: Exception) -> bool:
        """Detect permanent auth failures (401/403) so we can skip the dead provider."""
        text = str(exc).lower()
        auth_markers = ("401", "403", "unauthorized", "invalid key", "invalid_key", "authentication")
        return any(marker in text for marker in auth_markers)

    def _mark_provider_dead(self, name: str, exc: Exception) -> None:
        if name not in self._dead_providers:
            self._dead_providers.add(name)
            import warnings
            warnings.warn(
                f"Provider '{name}' returned auth error and is marked dead for this session: {exc}",
                RuntimeWarning,
                stacklevel=3,
            )

    def _mark_auth_failures_from_events(self, stage: str) -> None:
        for ev in self._fallback_events:
            if ev.get("stage") == stage and "error" in ev:
                err_text = str(ev["error"])
                if self._is_auth_error(RuntimeError(err_text)):
                    self._mark_provider_dead(str(ev.get("provider", "")), RuntimeError(err_text))


def _chain_call_kwargs(provider: Provider, kwargs: Mapping[str, Any]) -> Dict[str, Any]:
    call_kwargs = dict(kwargs)
    if getattr(provider, "name", "") == "anthropic":
        call_kwargs.setdefault("allow_fallback", False)
    return call_kwargs


def _is_live_provider_candidate(provider: Provider) -> bool:
    name = str(getattr(provider, "name", provider.__class__.__name__) or "").lower()
    model = str(getattr(provider, "model", "") or "").lower()
    if name == "mock" or model == "mock":
        return False
    return not bool(getattr(provider, "offline", False))
