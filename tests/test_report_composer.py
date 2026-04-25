"""Report Composer (C26) 테스트 — fake council_dir → MBB markdown 검증."""
import json
from pathlib import Path
import tempfile

from src.report import ReportComposer, compose_report


def _make_fake_council(tmp: Path) -> Path:
    """meta + 2 round × 2 persona fake council_dir."""
    council_dir = tmp / "council-test"
    council_dir.mkdir(parents=True)

    meta = {
        "council_id": "council-test",
        "topic": "MIRIVA 진단키트 가격 책정",
        "timestamp": "20260425T0000Z",
        "personas": [
            {"name": "이준혁", "role": "투자자",
             "expertise": ["벤처캐피털"],
             "perspective_bias": "수익성 우선",
             "argument_style": "데이터 기반"},
            {"name": "오태민", "role": "학술연구자",
             "expertise": ["학술 문헌"],
             "perspective_bias": "근거 기반",
             "argument_style": "엄밀"},
        ],
        "max_rounds": 2,
        "convergence_threshold": 0.7,
        "research_type": "analytical",
        "status": "round_1_prompts_generated",
    }
    (council_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False))

    # Round 1 — 시장 규모 chapter
    r1_lee = {
        "persona": "이준혁", "role": "투자자",
        "position": "조건부찬성",
        "key_points": ["TAM 200억원 / SAM 50억", "성장률 12% YoY"],
        "confidence": 0.75,
        "analysis": "한국 사과·배 농가 수 + 진단키트 침투율 5% 가정.",
        "evidence": [{"claim": "농촌진흥청 통계", "source": "rda.go.kr/2025"}],
        "framework_output": {"TAM": "200억", "SAM": "50억"},
    }
    r1_oh = {
        "persona": "오태민", "role": "학술연구자",
        "position": "중립",
        "key_points": ["출처 검증 필요", "샘플 size 불명"],
        "confidence": 0.55,
        "analysis": "TAM 산정 가정이 검증 안 됨.",
        "evidence": [],
    }
    (council_dir / "round-1-이준혁.json").write_text(
        json.dumps(r1_lee, ensure_ascii=False))
    (council_dir / "round-1-오태민.json").write_text(
        json.dumps(r1_oh, ensure_ascii=False))

    # Round 2 — 경쟁
    r2_lee = {
        "persona": "이준혁", "role": "투자자",
        "position": "찬성",
        "key_points": ["직접 경쟁자 2개 / 대체재 미미"],
        "confidence": 0.82,
        "analysis": "경쟁 강도 medium.",
        "evidence": [{"claim": "GreenLight Diagnostics 분석",
                      "source": "company-report.pdf"}],
    }
    r2_oh = {
        "persona": "오태민", "role": "학술연구자",
        "position": "조건부찬성",
        "key_points": ["대체재 학계 연구 동향 존재"],
        "confidence": 0.65,
        "analysis": "신규 진입 위협 high.",
        "evidence": [],
    }
    (council_dir / "round-2-이준혁.json").write_text(
        json.dumps(r2_lee, ensure_ascii=False))
    (council_dir / "round-2-오태민.json").write_text(
        json.dumps(r2_oh, ensure_ascii=False))

    return council_dir


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_compose_report_creates_file():
    with tempfile.TemporaryDirectory() as td:
        council_dir = _make_fake_council(Path(td))
        out = compose_report(council_dir)
        assert out.exists()
        assert out.name == "REPORT.md"
        assert out.stat().st_size > 500  # 의미있는 분량


def test_report_has_cover_topic_and_council_id():
    with tempfile.TemporaryDirectory() as td:
        council_dir = _make_fake_council(Path(td))
        composer = ReportComposer(council_dir)
        md = composer.render()
        assert "MIRIVA 진단키트 가격 책정" in md
        assert "council-test" in md
        assert "analytical" in md


def test_report_has_executive_summary():
    with tempfile.TemporaryDirectory() as td:
        council_dir = _make_fake_council(Path(td))
        md = ReportComposer(council_dir).render()
        assert "Executive Summary" in md
        assert "Net Position" in md
        assert "Average Confidence" in md
        assert "Position Distribution" in md


def test_report_has_table_of_contents():
    with tempfile.TemporaryDirectory() as td:
        council_dir = _make_fake_council(Path(td))
        md = ReportComposer(council_dir).render()
        assert "Table of Contents" in md
        assert "Chapter 1" in md
        assert "Chapter 2" in md


def test_report_chapter_includes_personas_and_evidence():
    with tempfile.TemporaryDirectory() as td:
        council_dir = _make_fake_council(Path(td))
        md = ReportComposer(council_dir).render()
        # Chapter 1: 시장 규모
        assert "시장 규모" in md
        assert "이준혁" in md
        assert "오태민" in md
        assert "TAM 200억원" in md
        assert "rda.go.kr" in md


def test_report_includes_framework_output():
    with tempfile.TemporaryDirectory() as td:
        council_dir = _make_fake_council(Path(td))
        md = ReportComposer(council_dir).render()
        assert "Framework Output" in md
        assert "TAM" in md and "200억" in md


def test_report_consensus_dissent_section():
    with tempfile.TemporaryDirectory() as td:
        council_dir = _make_fake_council(Path(td))
        md = ReportComposer(council_dir).render()
        assert "Cross-Round Consensus" in md
        assert "Dominant Position" in md


def test_report_appendix_personas():
    with tempfile.TemporaryDirectory() as td:
        council_dir = _make_fake_council(Path(td))
        md = ReportComposer(council_dir).render()
        assert "Appendix A" in md
        assert "벤처캐피털" in md  # expertise
        assert "근거 기반" in md  # bias


def test_report_appendix_evidence_index():
    with tempfile.TemporaryDirectory() as td:
        council_dir = _make_fake_council(Path(td))
        md = ReportComposer(council_dir).render()
        assert "Appendix B" in md
        assert "rda.go.kr/2025" in md
        assert "company-report.pdf" in md


def test_compose_with_missing_meta_returns_minimal():
    with tempfile.TemporaryDirectory() as td:
        empty = Path(td) / "empty"
        empty.mkdir()
        composer = ReportComposer(empty)
        md = composer.render()
        assert "Executive Summary" in md  # 빈 결과여도 헤더는 있어야


def test_compose_nonexistent_dir_raises():
    try:
        ReportComposer(Path("/nonexistent/path"))
        assert False
    except FileNotFoundError:
        pass
