from src.wiki.governance import build_dual_path_governance, validate_dual_path_governance


def test_dual_path_governance_separates_raw_source_and_wiki_markdown():
    record = build_dual_path_governance(
        artifact_id="report:abc/123",
        raw_source={"topic": "딸기 진단키트", "evidence": ["raw"]},
        wiki_markdown="# 딸기 진단키트\n\ncompiled truth\n",
    )

    assert record["raw_path"] == "raw/report-abc-123.json"
    assert record["wiki_path"] == "wiki/report-abc-123.md"
    assert record["index_path"] == "index/report-abc-123.json"
    assert record["manifest_path"] == "wiki/manifest.json"
    assert record["raw_sha256"] != record["wiki_sha256"]
    assert record["wiki_title"] == "딸기 진단키트"
    assert record["heading_count"] == 1
    assert record["maintenance_policy"]["raw_is_source_of_truth"] is True
    assert {entry["kind"] for entry in record["entries"]} == {
        "raw_source",
        "compiled_wiki",
        "search_index",
    }
    assert validate_dual_path_governance(record)


def test_dual_path_governance_indexes_links_and_source_ids():
    record = build_dual_path_governance(
        artifact_id="report-links",
        raw_source={
            "evidence": [
                {"id": "ref-1", "source_url": "https://example.test/a"},
                {"doi": "10.1234/example"},
            ]
        },
        wiki_markdown="# Page\n\nSee [source](https://example.test/a) and [[Related Page]].\n",
    )

    assert record["outbound_links"] == ["https://example.test/a", "Related Page"]
    assert "ref-1" in record["source_ids"]
    assert "https://example.test/a" in record["source_ids"]
    assert "10.1234/example" in record["source_ids"]
    assert record["source_count"] == 3
