import pytest

from src.runtime.iteration_hooks import HookRegistry, update_confidence


def test_hook_registry_fires_registered_callbacks_in_order():
    registry = HookRegistry()
    seen = []

    def first(context):
        context["round"] += 1
        seen.append(("first", context["round"]))
        return "first-result"

    def second(context):
        seen.append(("second", context["round"]))
        return "second-result"

    registry.register("pre_round", first)
    registry.register("pre_round", second)

    context = {"round": 0}
    results = registry.fire("pre_round", context)

    assert results == ["first-result", "second-result"]
    assert seen == [("first", 1), ("second", 1)]
    assert context == {"round": 1}


def test_hook_registry_keeps_events_independent():
    registry = HookRegistry()

    registry.register("pre_round", lambda context: context.setdefault("pre", True))
    registry.register("post_round", lambda context: context.setdefault("post", True))

    context = {}
    registry.fire("post_round", context)

    assert context == {"post": True}
    assert len(registry.callbacks_for("pre_round")) == 1
    assert len(registry.callbacks_for("post_round")) == 1


def test_hook_registry_rejects_unknown_event_and_non_mapping_context():
    registry = HookRegistry()

    with pytest.raises(ValueError, match="unsupported hook event"):
        registry.register("during_round", lambda context: None)

    with pytest.raises(TypeError, match="mutable mapping"):
        registry.fire("pre_round", [])  # type: ignore[arg-type]


def test_update_confidence_increases_decreases_and_combines_evidence():
    assert update_confidence(0.5, 0.8) == pytest.approx(0.8)
    assert update_confidence(0.8, 0.5) == pytest.approx(0.8)
    assert update_confidence(0.8, 0.2) == pytest.approx(0.5)

    combined = update_confidence(0.5, [0.8, 0.8])
    assert combined == pytest.approx(0.9411764705)


def test_update_confidence_validates_probability_bounds():
    with pytest.raises(ValueError, match="probability"):
        update_confidence(-0.1, 0.8)

    with pytest.raises(ValueError, match="probability"):
        update_confidence(0.5, 1.2)
