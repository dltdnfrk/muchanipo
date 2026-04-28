from __future__ import annotations

import json
from pathlib import Path

from src.governance.budget import PROVIDER_DEFAULT_MODELS, STAGE_PROVIDER_MODELS


def test_codex_router_config_matches_runtime_budget_defaults():
    config = json.loads(Path("config/model-router.json").read_text(encoding="utf-8"))

    codex = config["providers"]["codex"]

    assert codex["default"] == PROVIDER_DEFAULT_MODELS["codex"]
    assert codex["default"] == STAGE_PROVIDER_MODELS[("eval", "codex")]
    assert codex["default"] in codex["models"]
    assert f"-m {codex['default']}" in codex["access"]
