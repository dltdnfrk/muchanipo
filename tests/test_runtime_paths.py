import json

from conftest import load_script_module


paths = load_script_module("runtime_paths", "src/runtime/paths.py")
eval_agent = load_script_module("eval_agent_paths", "src/eval/eval-agent.py")


def test_get_vault_path_uses_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv(paths.ENV_VAULT_PATH, str(tmp_path))

    assert paths.get_vault_path("Feed") == tmp_path / "Feed"


def test_resolve_vault_path_setting_falls_back_for_unset_placeholder(monkeypatch):
    monkeypatch.delenv(paths.ENV_VAULT_PATH, raising=False)

    assert paths.resolve_vault_path_setting("${MUCHANIPO_VAULT_PATH}/Neobio") == (
        paths.DEFAULT_VAULT_PATH / "Neobio"
    )


def test_eval_agent_default_rubric_uses_config_rubric(repo_root):
    rubric = eval_agent.load_rubric(None)
    with open(repo_root / "config" / "rubric.json", "r", encoding="utf-8") as f:
        expected = json.load(f)

    assert rubric["version"] == expected["version"]
    assert paths.rubric_score_max(rubric) == 100
    assert rubric["thresholds"] == {"pass": 70, "uncertain": 50}
