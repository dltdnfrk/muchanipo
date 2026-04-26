"""Plateau detection (C2 task #17) — score 정체 자동 stop logic 검증."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def runner_module():
    spec = importlib.util.spec_from_file_location(
        "council_runner",
        Path("src/council/council-runner.py").resolve(),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mk_round(confidence: float, n_personas: int = 5) -> list[dict]:
    return [
        {"persona": f"p{i}", "position": "찬성", "confidence": confidence,
         "key_points": [], "evidence": []}
        for i in range(n_personas)
    ]


def test_plateau_skipped_when_few_rounds(runner_module):
    rounds = {1: _mk_round(0.5), 2: _mk_round(0.6)}
    plateau, reason = runner_module._detect_plateau(rounds, window=3)
    assert plateau is False
    assert "skipped" in reason


def test_plateau_detected_when_confidence_flat(runner_module):
    """3 round 연속 confidence 0.60-0.62 → plateau."""
    rounds = {1: _mk_round(0.4), 2: _mk_round(0.60), 3: _mk_round(0.61),
              4: _mk_round(0.62)}
    plateau, reason = runner_module._detect_plateau(rounds, window=3, tolerance=0.05)
    assert plateau is True
    assert "plateau detected" in reason
    assert "spread" in reason


def test_plateau_not_detected_when_growing(runner_module):
    """confidence 0.4 → 0.6 → 0.8 단조 증가 → no plateau."""
    rounds = {1: _mk_round(0.4), 2: _mk_round(0.6), 3: _mk_round(0.8)}
    plateau, reason = runner_module._detect_plateau(rounds, window=3, tolerance=0.05)
    assert plateau is False
    assert "no plateau" in reason


def test_plateau_uses_only_last_window(runner_module):
    """초기 큰 변동 + 마지막 3 round 평탄 → plateau."""
    rounds = {1: _mk_round(0.1), 2: _mk_round(0.9), 3: _mk_round(0.50),
              4: _mk_round(0.51), 5: _mk_round(0.52)}
    plateau, reason = runner_module._detect_plateau(rounds, window=3, tolerance=0.05)
    assert plateau is True


def test_plateau_tolerance_boundary(runner_module):
    """spread <= tolerance → plateau, spread > tolerance → no plateau."""
    rounds = {1: _mk_round(0.50), 2: _mk_round(0.53), 3: _mk_round(0.50)}
    plateau, _ = runner_module._detect_plateau(rounds, window=3, tolerance=0.05)
    assert plateau is True  # spread 0.03 ≤ 0.05
    # spread 0.10 명확히 초과
    rounds2 = {1: _mk_round(0.50), 2: _mk_round(0.60), 3: _mk_round(0.50)}
    plateau2, _ = runner_module._detect_plateau(rounds2, window=3, tolerance=0.05)
    assert plateau2 is False


def test_plateau_empty_results_skipped(runner_module):
    """빈 round → confidence 0.0 → spread 0 → plateau (edge case OK)."""
    rounds = {1: [], 2: [], 3: []}
    plateau, reason = runner_module._detect_plateau(rounds, window=3)
    # 모두 빈 결과 → 평균 0.0 동일 → plateau로 판정 (조기 stop 안전)
    assert plateau is True


def test_plateau_window_param(runner_module):
    """window=4 인 경우 4개 round 필요."""
    rounds = {1: _mk_round(0.5), 2: _mk_round(0.5), 3: _mk_round(0.5)}
    plateau, reason = runner_module._detect_plateau(rounds, window=4)
    assert plateau is False
    assert "skipped" in reason
