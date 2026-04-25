"""Iteration hook registry for MuchaNipo runtime loops.

pi-autoresearch style iteration hooks are intentionally small here: callers
can attach local callbacks around round and ratchet boundaries without pulling
in a plugin framework.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, MutableMapping


HookCallback = Callable[[MutableMapping[str, Any]], Any]


EVENTS: tuple[str, ...] = (
    "pre_round",
    "post_round",
    "pre_ratchet",
    "post_ratchet",
)


@dataclass
class HookRegistry:
    """라운드/ratchet 경계에서 실행할 callback을 관리한다."""

    _callbacks: dict[str, list[HookCallback]] = field(
        default_factory=lambda: defaultdict(list)
    )

    def __post_init__(self) -> None:
        for event in EVENTS:
            self._callbacks.setdefault(event, [])

    def register(self, event: str, callback: HookCallback) -> HookCallback:
        """Register a callback for one supported event and return it.

        Returning the callback keeps decorator-style usage possible:

            @registry.register("pre_round")
            def mark(context): ...
        """
        self._require_event(event)
        if not callable(callback):
            raise TypeError("callback must be callable")
        self._callbacks[event].append(callback)
        return callback

    def fire(self, event: str, context: MutableMapping[str, Any]) -> list[Any]:
        """Fire callbacks for event in registration order.

        The same mutable context is passed to every callback so lightweight
        runtime annotations can accumulate without a shared global object.
        """
        self._require_event(event)
        if not isinstance(context, MutableMapping):
            raise TypeError("context must be a mutable mapping")

        results: list[Any] = []
        for callback in list(self._callbacks[event]):
            results.append(callback(context))
        return results

    def callbacks_for(self, event: str) -> tuple[HookCallback, ...]:
        """Return a read-only snapshot of registered callbacks."""
        self._require_event(event)
        return tuple(self._callbacks[event])

    def registered_events(self) -> tuple[str, ...]:
        return EVENTS

    @staticmethod
    def _require_event(event: str) -> None:
        if event not in EVENTS:
            allowed = ", ".join(EVENTS)
            raise ValueError(f"unsupported hook event: {event!r}; allowed: {allowed}")


def update_confidence(prior: float, evidence: float | Iterable[float]) -> float:
    """Update confidence with a Bayesian odds transform.

    ``prior`` and each evidence value are probabilities in [0, 1]. Evidence
    above 0.5 increases posterior confidence; evidence below 0.5 decreases it.
    Exact 0/1 values are clamped to avoid infinite odds while preserving intent.
    """
    posterior = _clamp_probability(prior)
    values = [evidence] if isinstance(evidence, (int, float)) else list(evidence)

    for item in values:
        likelihood = _clamp_probability(float(item))
        prior_odds = posterior / (1.0 - posterior)
        likelihood_ratio = likelihood / (1.0 - likelihood)
        posterior_odds = prior_odds * likelihood_ratio
        posterior = posterior_odds / (1.0 + posterior_odds)

    return posterior


def _clamp_probability(value: float) -> float:
    if not 0.0 <= value <= 1.0:
        raise ValueError("probability must be between 0.0 and 1.0")
    epsilon = 1e-9
    return min(max(value, epsilon), 1.0 - epsilon)
