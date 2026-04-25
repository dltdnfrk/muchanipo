import pytest

from src.runtime import plugin_loader


def setup_function():
    plugin_loader._REGISTERED_SLOTS.clear()


def test_load_slot_from_default_config():
    impl = plugin_loader.load_slot("model_router")

    assert impl is plugin_loader.default_model_router
    assert impl()["provider"] == "default"


def test_register_slot_overrides_configured_slot():
    def custom_runtime():
        return {"runtime": "custom"}

    plugin_loader.register_slot("runtime", custom_runtime)

    assert plugin_loader.load_slot("runtime") is custom_runtime
    assert plugin_loader.load_slot("runtime")() == {"runtime": "custom"}


def test_load_notifier_slot_from_config():
    notifier = plugin_loader.load_slot("notifier")

    assert notifier is plugin_loader.default_notifier
    assert notifier("hello")["notified"] is False


def test_unknown_slot_reports_available_slots():
    with pytest.raises(plugin_loader.PluginSlotError) as excinfo:
        plugin_loader.load_slot("missing")

    message = str(excinfo.value)
    assert "unknown plugin slot: missing" in message
    assert "model_router" in message
    assert "runtime" in message


def test_config_parser_accepts_simple_slots_file(tmp_path, monkeypatch):
    config_path = tmp_path / "plugin-slots.yaml"
    config_path.write_text(
        """
slots:
  custom: src.runtime.plugin_loader:default_notifier  # inline comment
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(plugin_loader, "DEFAULT_CONFIG_PATH", config_path)

    assert plugin_loader.load_slot("custom") is plugin_loader.default_notifier


def test_import_target_must_be_callable(tmp_path, monkeypatch):
    config_path = tmp_path / "plugin-slots.yaml"
    config_path.write_text(
        "slots:\n  bad: src.runtime.plugin_loader:DEFAULT_CONFIG_PATH\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(plugin_loader, "DEFAULT_CONFIG_PATH", config_path)

    with pytest.raises(plugin_loader.PluginSlotError, match="not callable"):
        plugin_loader.load_slot("bad")
