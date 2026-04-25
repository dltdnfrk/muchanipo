"""Tests for src.dream.dream_runner — vault scan + dedup + cluster summary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.dream.dream_runner import DreamRunner, run_dream_cycle


def _seed_vault(root: Path) -> None:
    personas = root / "personas"
    insights = root / "insights"
    personas.mkdir(parents=True)
    insights.mkdir(parents=True)

    (personas / "farmer.md").write_text(
        "rice yield forecast needs rainfall context\n\n"
        "rice yield forecast needs rainfall context\n",
        encoding="utf-8",
    )
    (personas / "farmer-2.md").write_text(
        "rice yield forecast needs rainfall context\n",
        encoding="utf-8",
    )
    (insights / "soil.jsonl").write_text(
        json.dumps({"key": "soil-sensor", "content": "soil sensor drift observed"}) + "\n"
        + json.dumps({"key": "soil-sensor", "content": "soil sensor drift observed"}) + "\n"
        + json.dumps({"topic": "soil-sensor", "text": "maintenance ticket repeated"}) + "\n"
        + "{not valid json}\n"
        + json.dumps({"key": "weather", "content": "monsoon shift"}) + "\n",
        encoding="utf-8",
    )


def test_dream_runner_empty_vault_returns_zero_counts(tmp_path: Path) -> None:
    runner = DreamRunner(vault_root=tmp_path, threshold=2)
    report = runner.run()

    assert report.scanned_files == 0
    assert report.accumulated_episodes == 0
    assert report.clusters == []
    assert report.promoted == []
    assert "scanned_files: 0" in report.summary_text
    assert "(none)" in report.summary_text


def test_dream_runner_dedupes_and_promotes_clusters(tmp_path: Path) -> None:
    _seed_vault(tmp_path)
    runner = DreamRunner(vault_root=tmp_path, threshold=3)

    report = runner.run()

    assert report.scanned_files == 3
    assert report.accumulated_episodes >= 6
    assert "soil-sensor" in report.promoted
    assert "soil-sensor" in report.clusters
    # promoted clusters surface ahead of singletons in the ordered list
    assert report.clusters.index("soil-sensor") < report.clusters.index("weather")
    assert "weather" not in report.promoted
    assert "weather" in report.clusters


def test_dream_runner_writes_summary_when_output_dir_set(tmp_path: Path) -> None:
    _seed_vault(tmp_path)
    out_dir = tmp_path / "logs"

    report = run_dream_cycle(tmp_path, output_dir=out_dir, threshold=3)

    assert report.summary_path is not None
    assert report.summary_path.parent == out_dir
    body = report.summary_path.read_text(encoding="utf-8")
    assert "# Dream Cycle Summary" in body
    assert "soil-sensor" in body
    assert "promotion_threshold: 3" in body


def test_dream_runner_skips_unsupported_extensions(tmp_path: Path) -> None:
    (tmp_path / "personas").mkdir()
    (tmp_path / "personas" / "ignored.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (tmp_path / "personas" / "kept.md").write_text("monsoon shift across counties\n", encoding="utf-8")

    runner = DreamRunner(vault_root=tmp_path, threshold=1)
    report = runner.run()

    assert report.scanned_files == 1
    assert report.accumulated_episodes == 1


def test_dream_runner_cli_main_reports_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _seed_vault(tmp_path)
    from src.dream.dream_runner import main

    exit_code = main(
        [
            "--vault",
            str(tmp_path),
            "--threshold",
            "3",
            "--no-write",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["scanned_files"] == 3
    assert "soil-sensor" in payload["promoted"]
    assert payload["summary_path"] is None
