import json

from conftest import load_script_module


eval_agent = load_script_module("eval_agent_density", "src/eval/eval-agent.py")


def test_compute_density_score_high_density_report_scores_high():
    report_md = (
        "시장 규모는 2026년 1,200억원이며 전년 대비 18% 성장했다. "
        "출처: https://example.com/market\n\n"
        "전환율은 7.5%에서 9.1%로 상승했고 CAC는 32달러로 하락했다. "
        "source: ops dashboard"
    )

    score, reason = eval_agent._compute_density_score(report_md)

    assert score >= 8
    assert "numbers=" in reason
    assert "sources=" in reason


def test_compute_density_score_low_density_report_scores_low():
    report_md = (
        "시장은 좋아지고 있다.\n\n"
        "고객 반응도 긍정적이며 다음 단계로 확장할 수 있다."
    )

    score, reason = eval_agent._compute_density_score(report_md)

    assert score <= 2
    assert "paragraphs=2" in reason


def test_compute_density_score_empty_report_is_zero():
    score, reason = eval_agent._compute_density_score("  \n")

    assert score == 0
    assert reason == "report markdown empty"


def test_compute_coverage_breadth_scores_title_matches(tmp_path):
    layers = [
        {"chapter_title": "Market Size"},
        {"chapter_title": "Customer Pain"},
        {"chapter_title": "Go To Market"},
        {"chapter_title": "Risk Register"},
    ]
    (tmp_path / "round_layers.json").write_text(
        json.dumps(layers),
        encoding="utf-8",
    )
    (tmp_path / "REPORT.md").write_text(
        "# Market Size\n\n## Customer Pain\n\n## Risk Register\n",
        encoding="utf-8",
    )

    score, reason = eval_agent._compute_coverage_breadth(tmp_path)

    assert score == 8
    assert "covered_layers=3/4" in reason


def test_compute_coverage_breadth_missing_layers_is_zero(tmp_path):
    (tmp_path / "REPORT.md").write_text("# Market Size\n", encoding="utf-8")

    score, reason = eval_agent._compute_coverage_breadth(tmp_path)

    assert score == 0
    assert reason == "round layer chapter_title entries not found"


def test_evaluate_records_density_and_coverage_without_changing_total(tmp_path):
    layers = [
        {"chapter_title": "Market Size"},
        {"chapter_title": "Customer Pain"},
    ]
    (tmp_path / "round_layers.json").write_text(json.dumps(layers), encoding="utf-8")
    report_md = (
        "# Market Size\n\n"
        "Revenue reached 42억원 in 2026. 출처: https://example.com/revenue\n\n"
        "# Customer Pain\n\n"
        "Churn fell from 12% to 8%. source: customer dashboard"
    )
    (tmp_path / "REPORT.md").write_text(report_md, encoding="utf-8")

    rubric = {
        "version": "2.2.0",
        "thresholds": {"pass": 70, "uncertain": 50},
        "axes": {
            "usefulness": {"weight": 1.0, "max": 10},
            "density": {"weight": 0.0, "max": 10, "active_for_score": False},
            "coverage_breadth": {"weight": 0.0, "max": 10, "active_for_score": False},
        },
    }
    report = {
        "report_md": report_md,
        "council_dir": str(tmp_path),
        "recommendations": ["Implement a measured pilot with weekly review."],
        "consensus": "Useful operational report.",
        "confidence": 0.6,
    }

    result = eval_agent.evaluate(report, rubric)

    assert result["scores"]["density"] >= 8
    assert result["scores"]["coverage_breadth"] == 10
    assert result["total"] == result["scores"]["usefulness"]
