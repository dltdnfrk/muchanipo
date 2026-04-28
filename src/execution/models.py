"""Model gateway support layer.

The gateway stays mock-first for tests while allowing stage-specific real
providers to be swapped in behind the same small call interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from src.governance.budget import BudgetExceeded, provider_name, resolve_model


@dataclass
class ModelResult:
    text: str
    provider: str
    model: str = "mock"
    cost_usd: float = 0.0
    is_fallback: bool = False
    fallback_reason: str | None = None
    raw: Any = None


class Provider(Protocol):
    name: str

    def call(self, stage: str, prompt: str, **kwargs: Any) -> ModelResult:
        ...


class ModelGateway:
    """Route stage calls to providers and optionally enforce governance hooks."""

    def __init__(
        self,
        provider: Provider | None = None,
        *,
        providers: Mapping[str, Provider] | None = None,
        stage_routes: Mapping[str, str] | None = None,
        fallback_provider: Provider | None = None,
        budget: Any = None,
        audit: Any = None,
    ) -> None:
        self.provider = provider
        self.providers = dict(providers or {})
        self.stage_routes = dict(stage_routes or {})
        self.fallback_provider = fallback_provider
        self.budget = budget
        self.audit = audit

    def call(self, stage: str, prompt: str, **kwargs: Any) -> ModelResult:
        provider = self._provider_for(stage)
        reservation_id = None
        estimated_usd = 0.0
        if self.budget is not None:
            estimated_usd = self.budget.estimate(stage=stage, prompt=prompt, provider=provider)
            reservation_id = self.budget.reserve(
                stage=stage,
                estimated_usd=estimated_usd,
                provider=provider_name(provider),
                model=resolve_model(stage=stage, provider=provider),
            )
            if reservation_id is False:
                if self.fallback_provider is None:
                    raise BudgetExceeded("budget exceeded")
                fallback_reason = "budget exceeded"
                fallback_estimated_usd = self.budget.estimate(
                    stage=stage,
                    prompt=prompt,
                    provider=self.fallback_provider,
                )
                reservation_id = self.budget.reserve(
                    stage=stage,
                    estimated_usd=fallback_estimated_usd,
                    provider=provider_name(self.fallback_provider),
                    model=resolve_model(stage=stage, provider=self.fallback_provider),
                )
                if reservation_id is False:
                    raise BudgetExceeded("budget exceeded")
                result = self.dispatch(self.fallback_provider, stage=stage, prompt=prompt, **kwargs)
                result.is_fallback = True
                result.fallback_reason = fallback_reason
                actual_usd = float(getattr(result, "cost_usd", 0.0) or 0.0)
                self.budget.reconcile(reservation_id, actual_usd=actual_usd)
                self._audit(
                    stage,
                    self._provider_from_result(result, self.fallback_provider),
                    result,
                    actual_usd,
                    fallback_reason,
                )
                return result

        fallback_reason = None
        try:
            result = self.dispatch(provider, stage=stage, prompt=prompt, **kwargs)
        except Exception as exc:
            if self.fallback_provider is None:
                if reservation_id and self.budget is not None:
                    self.budget.reconcile(reservation_id, actual_usd=0.0)
                self._audit(stage, provider, None, estimated_usd, str(exc))
                raise
            fallback_reason = str(exc)
            if reservation_id and self.budget is not None:
                self.budget.reconcile(reservation_id, actual_usd=0.0)
                fallback_estimated_usd = self.budget.estimate(
                    stage=stage,
                    prompt=prompt,
                    provider=self.fallback_provider,
                )
                reservation_id = self.budget.reserve(
                    stage=stage,
                    estimated_usd=fallback_estimated_usd,
                    provider=provider_name(self.fallback_provider),
                    model=resolve_model(stage=stage, provider=self.fallback_provider),
                )
                if reservation_id is False:
                    raise BudgetExceeded("budget exceeded")
            result = self.dispatch(self.fallback_provider, stage=stage, prompt=prompt, **kwargs)
            result.is_fallback = True
            result.fallback_reason = fallback_reason

        actual_usd = float(getattr(result, "cost_usd", 0.0) or 0.0)
        if reservation_id and self.budget is not None:
            self.budget.reconcile(reservation_id, actual_usd=actual_usd)
        actual_provider = self._provider_from_result(result, self.fallback_provider or provider)
        self._audit(stage, actual_provider, result, actual_usd, fallback_reason)
        return result

    def dispatch(self, provider: Provider, *, stage: str, prompt: str, **kwargs: Any) -> ModelResult:
        if self.budget is not None and hasattr(self.budget, "dispatch"):
            return self.budget.dispatch(provider, stage=stage, prompt=prompt, **kwargs)
        return provider.call(stage=stage, prompt=prompt, **kwargs)

    def _provider_for(self, stage: str) -> Provider:
        route = self.stage_routes.get(stage)
        if route:
            try:
                return self.providers[route]
            except KeyError as exc:
                raise KeyError(f"stage {stage!r} routes to missing provider {route!r}") from exc
        if self.provider is not None:
            return self.provider
        if self.providers:
            return next(iter(self.providers.values()))
        raise ValueError("ModelGateway requires a provider or providers")

    def _audit(
        self,
        stage: str,
        provider: Provider,
        result: ModelResult | None,
        cost_usd: float,
        fallback_reason: str | None,
    ) -> None:
        if self.audit is None:
            return
        self.audit.record_call(
            stage=stage,
            provider=getattr(provider, "name", provider.__class__.__name__),
            model=getattr(result, "model", ""),
            cost_usd=cost_usd,
            fallback_reason=fallback_reason,
        )

    def _provider_from_result(self, result: ModelResult, default: Provider) -> Provider:
        result_provider = getattr(result, "provider", None)
        if isinstance(result_provider, str):
            return self.providers.get(result_provider, default)
        return default
