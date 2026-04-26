"""Frameworks Library (C25) 테스트."""

from src.frameworks import (
    JTBD,
    JobDimension,
    KPIDriver,
    MECENode,
    MECETree,
    NorthStarTree,
    Porter5Forces,
    ForceLevel,
    SWOT,
    framework_prompt_block,
    frameworks_for_layer,
)


# ----- Porter --------------------------------------------------------------
def test_porter_five_forces_render():
    p = Porter5Forces(
        threat_new_entrants=ForceLevel("med", "진입장벽 보통"),
        threat_substitutes=ForceLevel("low", "대체재 적음"),
        bargaining_buyers=ForceLevel("high", "buyer 가격 민감"),
        bargaining_suppliers=ForceLevel("med", "공급자 분산"),
        rivalry=ForceLevel("high", "5+ 경쟁자"),
        summary="rivalry+buyer 가장 위험",
    )
    md = p.to_markdown()
    assert "Porter 5 Forces" in md
    assert "신규 진입 위협" in md
    assert "🟢" in md and "🔴" in md
    assert "rivalry+buyer" in md


def test_force_level_invalid_severity_raises():
    try:
        ForceLevel("very-high", "x")
        assert False
    except ValueError:
        pass


# ----- JTBD ----------------------------------------------------------------
def test_jtbd_three_dimensions():
    j = JTBD(
        target_customer="한국 사과 농가",
        functional=JobDimension("functional", "병원체 빠르게 진단",
                                "샘플 보내고 3일 대기", "느리고 비쌈"),
        emotional=JobDimension("emotional", "농작물 잃을 불안 줄이기",
                               "수확 손실 후 후회", "예방 안 됨"),
        social=JobDimension("social", "이웃에 권하기 위한 신뢰",
                            "입소문 부재", "인지도 ↓"),
        fire_candidates=["기존 분광 진단"],
        hire_candidates=["MIRIVA 진단키트"],
    )
    md = j.to_markdown()
    assert "한국 사과 농가" in md
    assert "functional" in md
    assert "emotional" in md
    assert "social" in md
    assert "MIRIVA" in md


def test_jtbd_invalid_dimension_raises():
    try:
        JobDimension("financial", "x", "y", "z")
        assert False
    except ValueError:
        pass


# ----- SWOT ----------------------------------------------------------------
def test_swot_renders_all_quadrants():
    s = SWOT(
        strengths=["빠른 진단"],
        weaknesses=["고가"],
        opportunities=["과수화상병 확산"],
        threats=["규제 변동"],
        so_strategies=["빠른 진단 + 시장 확대"],
        wt_strategies=["가격 인하 + 규제 대응"],
    )
    md = s.to_markdown()
    assert "Strengths" in md
    assert "Weaknesses" in md
    assert "Opportunities" in md
    assert "Threats" in md
    assert "TOWS" in md


def test_swot_empty_renders_minimal():
    s = SWOT()
    md = s.to_markdown()
    assert "SWOT" in md


# ----- North Star Tree ------------------------------------------------------
def test_north_star_tree_with_drivers():
    t = NorthStarTree(
        north_star_metric="MAU",
        north_star_definition="월간 활성 농가 수",
        current_value="100",
        target_value="1000",
        drivers=[
            KPIDriver("회원가입 전환율", "5%", "10%", "weekly", "growth_lead"),
            KPIDriver("재진단 빈도", "0.5/m", "1.0/m", "monthly", "ops_lead"),
        ],
    )
    md = t.to_markdown()
    assert "MAU" in md
    assert "회원가입 전환율" in md
    assert "1000" in md
    assert "Driver Metrics" in md


def test_north_star_tree_no_drivers():
    t = NorthStarTree("revenue", "월매출")
    md = t.to_markdown()
    assert "revenue" in md


# ----- MECE Tree ------------------------------------------------------------
def test_mece_tree_renders_hierarchy():
    root = MECENode("MIRIVA 매출 어떻게 늘리나?")
    a = MECENode("신규 농가 늘리기", "현재 1000 농가")
    b = MECENode("재구매율 올리기")
    a.add_child(MECENode("마케팅 강화", is_leaf_hypothesis=True))
    a.add_child(MECENode("가격 인하", is_leaf_hypothesis=True))
    b.add_child(MECENode("로열티 프로그램", is_leaf_hypothesis=True))
    root.add_child(a)
    root.add_child(b)

    t = MECETree(root_question="MIRIVA 매출 ↑?", root=root)
    md = t.to_markdown()
    assert "MIRIVA 매출" in md
    assert "신규 농가" in md
    assert "🎯" in md  # leaf hypothesis 마커

    leaves = t.leaf_hypotheses()
    assert len(leaves) == 3


# ----- Registry -------------------------------------------------------------
def test_frameworks_for_layer_l2_porter():
    fws = frameworks_for_layer("L2_competitor_landscape")
    names = [n for n, _ in fws]
    assert "Porter 5 Forces" in names


def test_frameworks_for_layer_l3_jtbd():
    fws = frameworks_for_layer("L3_customer_jtbd")
    assert any("JTBD" in n for n, _ in fws)


def test_frameworks_for_layer_l8_north_star():
    fws = frameworks_for_layer("L8_metrics_kpi")
    assert any("North Star" in n for n, _ in fws)


def test_frameworks_for_layer_unknown_returns_empty():
    fws = frameworks_for_layer("L99_bogus")
    assert fws == []


def test_framework_prompt_block_includes_schema_hint():
    block = framework_prompt_block("L2_competitor_landscape")
    assert "Porter 5 Forces" in block
    assert "framework_output" in block
    assert "severity" in block


def test_framework_prompt_block_empty_for_no_framework():
    block = framework_prompt_block("L6_implementation_roadmap")
    assert block == ""
