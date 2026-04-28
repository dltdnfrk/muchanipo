import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_script_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def repo_root() -> Path:
    return ROOT


@pytest.fixture
def sample_evidence():
    return [
        {
            "id": "E1",
            "source": "market-brief",
            "quote": "MuchaNipo replay harness reduces manual regression review by 25% in 2026.",
            "source_text": "MuchaNipo replay harness reduces manual regression review by 25% in 2026.",
        },
        {
            "id": "E2",
            "source": "ops-note",
            "quote": "한국어 토큰 중첩 검증은 근거 문장과 핵심 주장을 비교한다.",
            "source_text": "한국어 토큰 중첩 검증은 근거 문장과 핵심 주장을 비교한다.",
        },
    ]


@pytest.fixture
def sample_council_report(repo_root: Path):
    with open(
        repo_root / "tests/fixtures/sample_council_report_v2.json",
        "r",
        encoding="utf-8",
    ) as f:
        return json.load(f)


@pytest.fixture
def unsupported_council_report(repo_root: Path):
    with open(
        repo_root / "tests/fixtures/sample_council_report_with_unsupported.json",
        "r",
        encoding="utf-8",
    ) as f:
        return json.load(f)
