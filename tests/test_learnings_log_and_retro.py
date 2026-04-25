"""LearningsLog + Retro (REFLECT 단계) 테스트."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path("src/intent")))
from learnings_log import LearningsLog, Learning  # type: ignore
from retro import Retro, Retrospective  # type: ignore


# ---------------------------------------------------------------------------
# LearningsLog
# ---------------------------------------------------------------------------
def test_learnings_log_add_and_read(tmp_path):
    log = LearningsLog(log_path=tmp_path / "learnings.jsonl")
    learning = log.add(
        key="korean-agtech-grounding",
        insight="Nemotron-Personas-Korea seed로 농가 페르소나가 grounded해짐",
        confidence=0.9,
        source="commit:8456d61",
    )
    assert isinstance(learning, Learning)
    all_l = log.all()
    assert len(all_l) == 1
    assert all_l[0].key == "korean-agtech-grounding"
    assert all_l[0].confidence == 0.9
    # JSONL 형식 검증
    lines = (tmp_path / "learnings.jsonl").read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["project_slug"] == "muchanipo"
    assert parsed["timestamp"]


def test_learnings_log_empty_key_raises(tmp_path):
    log = LearningsLog(log_path=tmp_path / "x.jsonl")
    try:
        log.add(key="", insight="x", confidence=0.5)
    except ValueError as e:
        assert "key" in str(e)
    else:
        assert False, "ValueError 기대"


def test_learnings_log_invalid_confidence_raises(tmp_path):
    log = LearningsLog(log_path=tmp_path / "x.jsonl")
    try:
        log.add(key="k", insight="i", confidence=1.5)
    except ValueError as e:
        assert "confidence" in str(e)
    else:
        assert False


def test_learnings_log_search_filters(tmp_path):
    log = LearningsLog(log_path=tmp_path / "x.jsonl")
    log.add(key="korean-grounding", insight="한국 도메인", confidence=0.9, source="a")
    log.add(key="english-test", insight="other", confidence=0.4, source="b")
    log.add(key="korean-citation", insight="citation grounding", confidence=0.7, source="c")

    # query 필터
    results = log.search("korean")
    assert len(results) == 2

    # confidence 필터
    high_conf = log.search("", min_confidence=0.6)
    assert len(high_conf) == 2  # 0.9 + 0.7
    assert all(l.confidence >= 0.6 for l in high_conf)


def test_learnings_log_prune_stale(tmp_path):
    log = LearningsLog(log_path=tmp_path / "x.jsonl")
    for i in range(10):
        log.add(key=f"k{i}", insight=f"i{i}", confidence=0.5, source="s")
    removed = log.prune_stale(max_entries=3)
    assert removed == 7
    remaining = log.all()
    assert len(remaining) == 3
    # 최신 3개 (k7, k8, k9)가 보존돼야
    keys = sorted([l.key for l in remaining])
    assert keys == ["k7", "k8", "k9"]


def test_learnings_log_export(tmp_path):
    log = LearningsLog(log_path=tmp_path / "log.jsonl")
    log.add(key="a", insight="x", confidence=0.5, source="s")
    log.add(key="b", insight="y", confidence=0.6, source="t")
    export_path = tmp_path / "exported.jsonl"
    n = log.export(export_path)
    assert n == 2
    assert export_path.exists()
    lines = export_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2


# ---------------------------------------------------------------------------
# Retro
# ---------------------------------------------------------------------------
def test_retro_summarize_pass_verdict(tmp_path):
    log = LearningsLog(log_path=tmp_path / "learnings.jsonl")
    retro = Retro(log=log)
    eval_result = {
        "scores": {
            "usefulness": 8, "reliability": 9, "novelty": 7, "actionability": 8,
            "completeness": 9, "evidence_quality": 9, "perspective_diversity": 8,
            "coherence": 9, "depth": 8, "impact": 8,
        },
        "grounding": {"verified_claim_ratio": 0.92, "unsupported_critical_claim_count": 0},
    }
    council_report = {
        "consensus": "MIRIVA 진단키트는 농가 가격 1만원 이하가 적정",
        "dissent": "",
        "open_questions": ["수출 시장은?"],
        "personas": [{"name": "p1", "confidence": 0.8}, {"name": "p2", "confidence": 0.85}],
    }
    r = retro.summarize(
        council_id="council-test-001",
        topic="MIRIVA 가격 책정",
        verdict="PASS",
        score=83.0,
        eval_result=eval_result,
        council_report=council_report,
        rounds=3,
        duration_minutes=12.5,
    )
    assert isinstance(r, Retrospective)
    assert r.verdict == "PASS"
    assert r.score == 83.0
    assert len(r.what_went_well) >= 1
    assert any("PASS" in w for w in r.what_went_well)
    # learnings가 LearningsLog에 누적됨
    all_l = log.all()
    assert len(all_l) >= 2  # verdict + grounding
    assert any("verdict" in l.key for l in all_l)
    assert any("grounding" in l.key for l in all_l)


def test_retro_summarize_fail_with_unsupported_claims(tmp_path):
    log = LearningsLog(log_path=tmp_path / "learnings.jsonl")
    retro = Retro(log=log)
    eval_result = {
        "scores": {
            "citation_fidelity": 2, "usefulness": 5, "reliability": 4, "depth": 3,
        },
        "grounding": {"verified_claim_ratio": 0.3, "unsupported_critical_claim_count": 4},
    }
    r = retro.summarize(
        council_id="council-test-002",
        topic="검증 부족 토픽",
        verdict="FAIL",
        score=42.0,
        eval_result=eval_result,
        council_report={"consensus": "", "dissent": "", "open_questions": []},
    )
    assert r.verdict == "FAIL"
    assert any("FAIL" in f or "unsupported" in f for f in r.what_failed)
    # 약한 축이 fail에 잡혀야
    assert any("citation_fidelity" in f or "depth" in f for f in r.what_failed)
    # weakest-axis learning이 누적되어야
    all_l = log.all()
    assert any("weakest" in l.key for l in all_l)


def test_retro_extracts_dissent_surprises(tmp_path):
    log = LearningsLog(log_path=tmp_path / "learnings.jsonl")
    retro = Retro(log=log)
    long_dissent = (
        "이 결론은 한국 농가 평균 소득 가정에 의존하지만, 제주 감귤 농가는 다르다. "
        "수출 비중과 가공 채널이 큰 변수이며 단순 평균이 의미를 잃을 수 있다. " * 3
    )
    council_report = {
        "consensus": "기본 가격 1만원",
        "dissent": long_dissent,
        "personas": [
            {"name": "a", "confidence": 0.95},
            {"name": "b", "confidence": 0.35},
        ],
    }
    r = retro.summarize(
        council_id="council-test-003",
        topic="가격 책정",
        verdict="UNCERTAIN",
        score=60.0,
        eval_result={"scores": {}, "grounding": {}},
        council_report=council_report,
    )
    # confidence spread + 강한 dissent 둘 다 surprise로 잡혀야
    assert len(r.surprises) >= 1
    surprises_joined = " ".join(r.surprises)
    assert "spread" in surprises_joined or "dissent" in surprises_joined


def test_retro_to_progress_entry_markdown(tmp_path):
    log = LearningsLog(log_path=tmp_path / "x.jsonl")
    retro = Retro(log=log)
    r = retro.summarize(
        council_id="c-9",
        topic="test",
        verdict="PASS",
        score=75.0,
        eval_result={"scores": {"usefulness": 8}, "grounding": {}},
        council_report={"open_questions": ["다음 단계?"]},
    )
    entry = r.to_progress_entry()
    assert "## Exp#c-9" in entry
    assert "PASS" in entry
    assert "후속 질문" in entry
