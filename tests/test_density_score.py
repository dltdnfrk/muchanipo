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


# ---------------------------------------------------------------------------
# Codex critic Major #1 fix — rubric-learner measurement-only axis exclusion
# ---------------------------------------------------------------------------
import json as _json
import importlib.util as _ilu
from pathlib import Path as _Path


def _load_rubric_learner():
    spec = _ilu.spec_from_file_location("rl", _Path("src/eval/rubric-learner.py"))
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_axis_weight_adjustment_excludes_measurement_only_axes(tmp_path):
    rl = _load_rubric_learner()
    rubric = {
        "axes": {
            "usefulness": {"weight": 1.0},
            "actionability": {"weight": 1.0},
            "density": {"weight": 0.0, "active_for_score": False},
            "coverage_breadth": {"weight": 0.0, "active_for_score": False},
        }
    }
    feedback = [
        {
            "interest_axis": "x",
            "action": "reject",
            "scores": {"usefulness": 6, "actionability": 5},
        }
        for _ in range(3)
    ]
    proposals = [{"type": "axis_weight_adjustment", "data": {"interest_axis": "x"}}]
    proposed_changes = []
    for p in proposals:
        ptype = p["type"]
        data = p["data"]
        if ptype == "axis_weight_adjustment":
            ia = data.get("interest_axis", "")
            ia_rejects = [
                e for e in feedback
                if e.get("interest_axis") == ia and e.get("action") == "reject"
            ]
            if ia_rejects:
                axis_avgs = {}
                axes_cfg = rubric.get("axes", {})
                for axis in rl.AXES:
                    cfg = axes_cfg.get(axis, {})
                    if cfg.get("weight", 1.0) == 0 or cfg.get("active_for_score") is False:
                        continue
                    vals = [
                        e["scores"][axis]
                        for e in ia_rejects
                        if isinstance(e.get("scores"), dict) and axis in e["scores"]
                    ]
                    if not vals:
                        continue
                    axis_avgs[axis] = sum(vals) / len(vals)
                # density / coverage_breadth는 절대 axis_avgs에 없어야
                assert "density" not in axis_avgs
                assert "coverage_breadth" not in axis_avgs
                # 그리고 lowest는 actionability(5)이어야
                if axis_avgs:
                    lowest = min(axis_avgs, key=lambda a: axis_avgs[a])
                    assert lowest == "actionability"
