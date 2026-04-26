"""Round Layers (C24) 테스트 — 10 layer × Type-aware 매핑."""

from src.council.round_layers import (
    DEFAULT_LAYERS,
    RoundLayer,
    all_layer_ids,
    layer_prompt_block,
    select_layer_for_round,
)


def test_default_has_ten_layers():
    assert len(DEFAULT_LAYERS) == 10
    ids = all_layer_ids()
    assert "L1_market_sizing" in ids
    assert "L10_executive_synthesis" in ids


def test_layer_ids_are_unique():
    ids = all_layer_ids()
    assert len(ids) == len(set(ids))


def test_each_layer_has_required_fields():
    for layer in DEFAULT_LAYERS:
        assert layer.layer_id
        assert layer.chapter_title
        assert layer.focus_question
        assert isinstance(layer.emphasis_roles, list) and layer.emphasis_roles
        assert isinstance(layer.evidence_kinds, list) and layer.evidence_kinds
        assert layer.success_signal


def test_select_layer_full_10_round_mapping():
    for n in range(1, 11):
        layer = select_layer_for_round(n, total_rounds=10)
        assert layer.layer_id == DEFAULT_LAYERS[n - 1].layer_id


def test_select_layer_short_run_uses_must_layers():
    """3 round 짧은 실행 — L1, L10 항상 포함."""
    selected_ids = [
        select_layer_for_round(n, total_rounds=3, research_type="exploratory").layer_id
        for n in range(1, 4)
    ]
    assert "L1_market_sizing" in selected_ids
    assert "L10_executive_synthesis" in selected_ids


def test_select_layer_analytical_boost():
    """analytical type → financial/risk/metrics layer 우선."""
    selected_ids = [
        select_layer_for_round(n, total_rounds=5, research_type="analytical").layer_id
        for n in range(1, 6)
    ]
    boost_layers = {"L4_financial_model", "L5_risk_scenario", "L8_metrics_kpi"}
    overlap = boost_layers & set(selected_ids)
    assert len(overlap) >= 2


def test_select_layer_comparative_boost():
    selected_ids = [
        select_layer_for_round(n, total_rounds=5, research_type="comparative").layer_id
        for n in range(1, 6)
    ]
    boost_layers = {"L2_competitor_landscape", "L3_customer_jtbd",
                    "L9_counterargs_sensitivities"}
    overlap = boost_layers & set(selected_ids)
    assert len(overlap) >= 2


def test_select_layer_predictive_boost():
    selected_ids = [
        select_layer_for_round(n, total_rounds=4, research_type="predictive").layer_id
        for n in range(1, 5)
    ]
    boost_layers = {"L6_implementation_roadmap", "L7_governance_ops"}
    overlap = boost_layers & set(selected_ids)
    assert len(overlap) >= 1


def test_select_layer_invalid_round_raises():
    try:
        select_layer_for_round(0)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_layer_prompt_block_has_focus_and_evidence():
    layer = DEFAULT_LAYERS[0]  # L1_market_sizing
    block = layer_prompt_block(layer)
    assert "Focus Question" in block
    assert "evidence" in block.lower()
    assert "강조 역할" in block
    assert "성공 기준" in block
    assert layer.chapter_title in block


def test_layer_prompt_block_returns_markdown():
    block = layer_prompt_block(DEFAULT_LAYERS[9])  # L10
    assert block.startswith("## 📑")
