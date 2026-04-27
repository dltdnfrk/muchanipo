"""Model Gateway v2 — PRD §8.1 stage routing + multi-step fallback chain.

Stage routing per PRD-v2 §8.1 (Qwen 보류):
    Intake     → Gemini (Flash)
    Interview  → Anthropic Sonnet
    Targeting  → Gemini
    Research   → Gemini + Kimi (parallel — chosen by caller)
    Evidence   → Kimi
    Council    → Anthropic Opus
    Report     → Anthropic Sonnet  (Qwen 로컬 보류)
    Eval       → Codex (GPT-5.5)

Fallback chain per stage — first failure → next provider in chain.
Offline mode is opt-in: if KIMI_OFFLINE / GEMINI_OFFLINE / CODEX_OFFLINE / no
API keys, providers return deterministic mocks (test-friendly).

stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence

from src.execution.models import ModelGateway, ModelResult, Provider


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
    # Convenience aliases used elsewhere
    "consensus": "anthropic",
    "ingest":    "gemini",
}


# Per-stage fallback chain — provider names tried in order on failure.
FALLBACK_CHAIN: Dict[str, List[str]] = {
    "intake":    ["gemini", "anthropic", "mock"],
    "interview": ["anthropic", "gemini", "mock"],
    "targeting": ["gemini", "anthropic", "mock"],
    "research":  ["gemini", "kimi", "anthropic", "mock"],
    "evidence":  ["kimi", "gemini", "anthropic", "mock"],
    "council":   ["anthropic", "gemini", "mock"],
    "report":    ["anthropic", "gemini", "mock"],
    "eval":      ["codex", "anthropic", "mock"],
    "consensus": ["anthropic", "gemini", "mock"],
    "ingest":    ["gemini", "anthropic", "mock"],
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
                result = provider.call(stage=stage, prompt=prompt, **kwargs)
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
) -> Dict[str, Provider]:
    """기본 5종 provider (anthropic/gemini/kimi/codex/mock).

    force_offline=True면 모든 LLM provider를 offline 모드로 강제 — 테스트용.
    """
    from src.execution.providers.anthropic import AnthropicProvider
    from src.execution.providers.codex import CodexProvider
    from src.execution.providers.gemini import GeminiProvider
    from src.execution.providers.kimi import KimiProvider
    from src.execution.providers.mock import MockProvider

    providers: Dict[str, Provider] = {
        "anthropic": AnthropicProvider(),
        "gemini": GeminiProvider(offline=True if force_offline else None),
        "kimi": KimiProvider(offline=True if force_offline else None),
        "codex": CodexProvider(offline=True if force_offline else None),
        "mock": MockProvider(),
    }
    return providers


def default_gateway(
    *,
    providers: Optional[Mapping[str, Provider]] = None,
    routes: Optional[Mapping[str, str]] = None,
    fallback_chain: Optional[Mapping[str, Sequence[str]]] = None,
    budget: Any = None,
    audit: Any = None,
    force_offline: bool = False,
) -> "GatewayV2":
    """PRD §8.1 기본 라우팅 + fallback chain을 갖춘 GatewayV2 인스턴스."""
    provider_map = dict(providers) if providers else build_default_providers(force_offline=force_offline)
    return GatewayV2(
        providers=provider_map,
        stage_routes=dict(routes or PRIMARY_ROUTES),
        fallback_chain=dict(fallback_chain or FALLBACK_CHAIN),
        budget=budget,
        audit=audit,
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

    def call(self, stage: str, prompt: str, **kwargs: Any) -> ModelResult:
        chain_names = self.fallback_chain.get(stage)
        if not chain_names:
            # 체인 미정의 → 기본 ModelGateway 동작
            return super().call(stage, prompt, **kwargs)

        chain_providers: List[Provider] = []
        for name in chain_names:
            prov = self.providers.get(name)
            if prov is not None:
                chain_providers.append(prov)
        if not chain_providers:
            raise KeyError(f"stage {stage!r} fallback chain has no resolvable providers")

        reservation_id = None
        estimated_usd = 0.0
        primary = chain_providers[0]
        if self.budget is not None:
            estimated_usd = self.budget.estimate(stage=stage, prompt=prompt, provider=primary)
            reservation_id = self.budget.reserve(stage=stage, estimated_usd=estimated_usd)

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
            raise

        actual_usd = float(getattr(result, "cost_usd", 0.0) or 0.0)
        if reservation_id and self.budget is not None:
            self.budget.reconcile(reservation_id, actual_usd=actual_usd)
        self._audit(stage, primary, result, actual_usd, result.fallback_reason)
        return result

    def _record_fallback(self, stage: str, provider: Provider, error: Exception) -> None:
        self._fallback_events.append({
            "stage": stage,
            "provider": getattr(provider, "name", str(provider)),
            "error": str(error),
        })

    @property
    def fallback_events(self) -> List[Dict[str, Any]]:
        return list(self._fallback_events)
