import json

import pytest

from src.report.composer import ReportComposer
from src.report.visual_wire import VisualWire


def test_porter_5_forces_builds_5x3_markdown_table():
    block = VisualWire.build_chart_block(
        {
            "framework": "Porter 5 Forces",
            "threat_new_entrants": {"severity": "high", "rationale": "Low switching cost"},
            "threat_substitutes": {"severity": "med", "rationale": "Manual diagnosis remains"},
            "bargaining_buyers": {"severity": "high", "rationale": "Few buyers"},
            "bargaining_suppliers": {"severity": "low", "rationale": "Commodity reagents"},
            "rivalry": {"severity": "med", "rationale": "Two direct competitors"},
        }
    )

    assert "| Force | Severity | Rationale |" in block
    assert block.count("\n|") == 6
    assert "Threat of New Entrants" in block
    assert "Low switching cost" in block


def test_jtbd_builds_three_axis_markdown_table():
    block = VisualWire.build_chart_block(
        {
            "framework": "JTBD",
            "functional": {"job": "Detect disease early", "current_solution": "Manual scouting", "gap": "Slow"},
            "emotional": {"job": "Feel confident", "current_solution": "Expert calls", "gap": "Uncertain"},
            "social": {"job": "Show diligence", "current_solution": "Paper logs", "gap": "Hard to share"},
        }
    )

    assert "| Dimension | Job | Current Solution | Gap |" in block
    assert "| functional | Detect disease early | Manual scouting | Slow |" in block
    assert "| emotional | Feel confident | Expert calls | Uncertain |" in block
    assert "| social | Show diligence | Paper logs | Hard to share |" in block


def test_north_star_tree_builds_mermaid_graph():
    block = VisualWire.build_chart_block(
        {
            "framework": "North Star Tree",
            "north_star_metric": "Weekly verified diagnoses",
            "drivers": [{"name": "Active farms"}, {"name": "Tests per farm"}],
        }
    )

    assert block.startswith("```mermaid\ngraph TD")
    assert 'north_star["Weekly verified diagnoses"]' in block
    assert "north_star --> driver_1_active_farms" in block
    assert "north_star --> driver_2_tests_per_farm" in block


def test_mece_tree_builds_mermaid_graph_with_branches_and_leaves():
    block = VisualWire.build_chart_block(
        {
            "framework": "MECE Tree",
            "root": "Market sizing",
            "branches": [
                {"label": "TAM", "leaves": ["Apple farms", "Pear farms"]},
                {"label": "SAM", "leaves": ["Greenhouse farms"]},
            ],
        }
    )

    assert block.startswith("```mermaid\ngraph TD")
    assert 'root["Market sizing"]' in block
    assert "root --> root_1_1_tam" in block
    assert "root_1_1_tam --> root_1_1_tam_2_1_apple_farms" in block


def test_swot_builds_2x2_markdown_table():
    block = VisualWire.build_chart_block(
        {
            "framework": "SWOT",
            "strengths": ["fast assay"],
            "weaknesses": ["cold-chain dependency"],
            "opportunities": ["export grants"],
            "threats": ["subsidized incumbents"],
        }
    )

    assert "|  | Positive | Negative |" in block
    assert "| Internal | fast assay | cold-chain dependency |" in block
    assert "| External | export grants | subsidized incumbents |" in block


def test_composer_uses_visual_block_instead_of_raw_json(tmp_path):
    council_dir = tmp_path / "council"
    council_dir.mkdir()
    (council_dir / "round-1-analyst.json").write_text(
        json.dumps(
            {
                "persona": "Analyst",
                "role": "strategy",
                "position": "찬성",
                "confidence": 0.8,
                "framework_output": {
                    "framework": "SWOT",
                    "strengths": ["fast assay"],
                    "weaknesses": ["cold-chain dependency"],
                    "opportunities": ["export grants"],
                    "threats": ["subsidized incumbents"],
                },
            }
        ),
        encoding="utf-8",
    )

    report = ReportComposer(council_dir).render()

    assert "**Framework Output:**" in report
    assert "| Internal | fast assay | cold-chain dependency |" in report
    assert "```json" not in report


@pytest.mark.parametrize(
    ("framework_output", "expected"),
    [
        (
            {
                "type": "Porter 5 Forces",
                "forces": [
                    {"force": "Entrants", "severity": "high", "rationale": "Open channel"},
                    {"force": "Substitutes", "severity": "low", "rationale": "Weak alternatives"},
                ],
            },
            "Entrants",
        ),
        ({"name": "JTBD", "dimensions": [{"dimension": "functional", "job": "Measure", "current": "Manual", "pain": "Late"}]}, "Measure"),
        ({"type": "North Star", "north_star": "Paid diagnostic runs", "drivers": {"activation": {"target": "30%"}}}, "activation"),
        ({"type": "MECE", "root": {"label": "Profit", "children": [{"label": "Revenue"}]}}, "Profit"),
        ({"type": "SWOT", "strengths": ["IP"], "weaknesses": ["CAC"], "opportunities": ["Export"], "threats": ["FX"]}, "Export"),
        ({"framework_type": "porter", "threat_new_entrants": "high"}, "high"),
        ({"framework_type": "jobs to be done", "emotional": {"job": "Trust result"}}, "Trust result"),
        ({"framework_type": "north star tree", "north_star_metric": "Retained labs"}, "Retained labs"),
        ({"framework_type": "mece tree", "root_question": "Where to win?", "children": ["Segment A"]}, "Segment A"),
        ({"framework_type": "swot analysis", "threats": ["Regulation"]}, "Regulation"),
        ({"drivers": [{"driver": "repeat usage"}], "north_star_metric": "Weekly users"}, "repeat usage"),
        ({"branches": [{"name": "Cost", "children": [{"name": "COGS"}]}], "root": "Margin"}, "COGS"),
        ({"dimensions": [{"dimension": "social", "job": "Signal diligence"}]}, "Signal diligence"),
        ({"strengths": "speed", "weaknesses": "fragility"}, "fragility"),
        ({"threat_substitutes": {"level": "med", "reason": "Adjacent products"}}, "Adjacent products"),
        ({"framework": "SWOT", "strengths": ["fast | robust"]}, "fast \\| robust"),
        ({"framework": "JTBD", "functional": {"job": ["detect", "triage"]}}, "detect<br>triage"),
        ({"framework": "Porter 5 Forces", "rivalry": {"severity": "high", "why": "crowded"}}, "crowded"),
        ({"framework": "North Star Tree", "metric": "Activated hectares", "drivers": ["coverage"]}, "coverage"),
        ({"framework": "MECE Tree", "question": "Adoption", "children": {"Farm size": ["small", "large"]}}, "large"),
        ({"framework": "SWOT", "opportunities": {"grant": "regional"}, "threats": {"policy": "delay"}}, "policy: delay"),
        ({"framework": "JTBD", "functional": {"desired_job": "Reduce crop loss"}}, "Reduce crop loss"),
        ({"framework": "Porter 5 Forces", "forces": [{"name": "Buyer power", "level": "high", "reason": "Procurement"}]}, "Procurement"),
        ({"framework": "North Star Tree", "north_star": "Resolved incidents", "drivers": [{"metric": "first response"}]}, "first response"),
        ({"framework": "MECE Tree", "root": "Growth", "branches": {"Channels": {"leaves": ["direct"]}}}, "direct"),
    ],
)
def test_visual_wire_handles_framework_aliases_and_shapes(framework_output, expected):
    assert expected in VisualWire.build_chart_block(framework_output)


# ---------------------------------------------------------------------------
# Codex critic Major #2 fix — Mermaid label escaping
# ---------------------------------------------------------------------------
def test_mermaid_north_star_escapes_quotes():
    out = VisualWire.build_chart_block({
        "framework": "north_star",
        "north_star": 'A"B',
        "drivers": [{"name": 'Driver"X'}],
    })
    # quote가 raw로 들어가면 mermaid 깨짐. &quot; entity로 escape돼야.
    assert '"A"B"' not in out
    assert "&quot;" in out


def test_mermaid_mece_escapes_brackets_and_hash():
    out = VisualWire.build_chart_block({
        "framework": "mece",
        "root": "[Q] #1",
        "branches": [{"label": 'Child"with quote'}],
    })
    assert "&quot;" in out
    assert "&#91;" in out or "&#93;" in out
    assert "&#35;" in out
