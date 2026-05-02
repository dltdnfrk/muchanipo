from src.wiki.gbrain_runtime import (
    brain_first_lookup,
    build_gbrain_runtime_record,
    validate_gbrain_runtime_record,
)


def test_gbrain_runtime_builds_page_event_graph_and_brain_first_route():
    record = build_gbrain_runtime_record(
        artifact_id="report-1",
        topic="딸기 진단키트 시장성",
        compiled_truth="## Compiled Truth\n\n딸기 농가의 현장 진단키트 수요는 검증 대상이다.\n",
        raw_source={
            "tags": ["agtech"],
            "evidence": [
                "ref-1: OpenAlex — tissue culture market",
                "ref-2: Crossref — disease-free seedlings",
            ],
            "personas": [{"name": "농가 구매자", "role": "buyer"}],
            "open_questions": ["가격 민감도 검증"],
            "consensus": "근거를 더 수집하되 go/no-go 기준은 명확하다.",
        },
        evidence_summary={"trusted": 2, "verified_claim_ratio": 1.0},
        content_hash="abc123",
        timeline_entry="2026-05-02 | PASS | score=80/100 | council_id=report-1",
    )

    assert validate_gbrain_runtime_record(record)
    assert record["valid"] is True
    assert record["upstream"]["license"] == "MIT"
    assert record["page"]["slug"] == "딸기-진단키트-시장성"
    assert record["page"]["event_count"] >= 3
    assert record["page"]["link_count"] >= 4
    assert record["brain_first_route"] == ["search", "query", "get_page", "external_after_empty"]
    assert record["search_index"]["mode"] == "keyword_graph_hybrid"
    assert record["source_attribution"]["source_ids"] == ["ref-1", "ref-2"]
    assert {link["type"] for link in record["typed_links"]} >= {
        "cites",
        "mentions_persona",
        "has_open_question",
        "filed_under",
    }
    assert all(event["append_only"] for event in record["event_ledger"])


def test_brain_first_lookup_prefers_local_record_before_external_search():
    record = build_gbrain_runtime_record(
        artifact_id="report-2",
        topic="무병묘 공급망",
        compiled_truth="## Compiled Truth\n\n무병묘 공급망은 농가 수요와 생산 병목을 함께 봐야 한다.\n",
        raw_source={"evidence": ["ref-1: DOI — seedling supply"]},
        evidence_summary={"trusted": 1, "verified_claim_ratio": 1.0},
        content_hash="hash",
        timeline_entry="2026-05-02 | PASS | score=90/100 | council_id=report-2",
    )

    local = brain_first_lookup("무병묘 공급망 병목", [record])
    missing = brain_first_lookup("전혀없는검색어", [record])

    assert local["external_allowed"] is False
    assert local["results"][0]["slug"] == "무병묘-공급망"
    assert local["results"][0]["route"] == "search+graph_boost"
    assert missing["external_allowed"] is True
