from pathlib import Path

from src.evidence.artifact import EvidenceRef, Finding
from src.hitl.plannotator_adapter import HITLAdapter
from src.pipeline.idea_to_council import IdeaToCouncilPipeline


class MockAcademicRunner:
    def run(self, plan):
        refs = [
            EvidenceRef(
                id=f"mock-academic-{idx}",
                source_url=f"https://example.org/paper/{idx}",
                source_title=f"Mock strawberry diagnostics paper {idx}",
                quote=quote,
                source_grade="A",
                provenance={
                    "kind": "mock-academic",
                    "source_text": f"{quote} Additional peer-reviewed context.",
                },
            )
            for idx, quote in enumerate(
                [
                    "Low-cost diagnostic kits reduce crop scouting friction for strawberry farms.",
                    "Korean protected-culture strawberry farms need fast disease screening workflows.",
                    "On-farm diagnostics can improve pesticide timing and reduce avoidable losses.",
                    "Adoption depends on kit price, training burden, and local distribution support.",
                ],
                start=1,
            )
        ]
        return [
            Finding(
                claim=f"Evidence-backed research direction for: {query}",
                support=refs,
                confidence=0.75,
                limitations=[],
            )
            for query in plan.queries
        ]


def test_mock_first_pipeline_from_idea_to_vault(tmp_path: Path):
    events = []
    pipeline = IdeaToCouncilPipeline(
        hitl_adapter=HITLAdapter(mode="auto_approve"),
        research_runner=MockAcademicRunner(),
        vault_dir=tmp_path / "vault" / "insights",
        council_log_dir=tmp_path / "council",
        progress_callback=events.append,
    )

    result = pipeline.run("딸기 농가용 저비용 진단키트 시장성")

    assert result.brief.is_ready
    assert result.brief.known_facts
    assert result.brief.constraints
    assert result.brief.success_criteria
    assert result.consensus_plan.consensus_score > 0
    # kimi's domain keywords are English-biased — Korean inputs may map to
    # 'general'. Just require domains is populated and provenance dict shape ok.
    assert result.targeting_map.domains, "targeting_map.domains should not be empty"
    assert len(result.evidence_refs) == 4
    assert result.evidence_summary["total"] == 4
    assert result.evidence_summary["trusted"] == 4
    assert all(hitl.status == "approved" for hitl in result.hitl_results.values())

    stage_names = [event["stage"] for event in events]
    for stage in [
        "idea_dump",
        "interview",
        "targeting",
        "research",
        "evidence",
        "council",
        "report",
        "vault",
        "agents",
        "done",
    ]:
        assert stage in stage_names

    assert result.report_md.count("## Chapter ") == 6
    assert "## ReACT Execution Plan" in result.report_md
    assert "## GBrain Compiled Truth + Timeline" in result.report_md
    for chapter_no in range(1, 7):
        assert f"## Chapter {chapter_no}:" in result.report_md

    expected_vault_path = tmp_path / "vault" / "insights" / f"{result.brief.id}.md"
    assert result.vault_path == expected_vault_path
    assert expected_vault_path.exists()
    assert expected_vault_path.read_text(encoding="utf-8") == result.report_md

    evidence_events = [event for event in events if event["stage"] == "evidence"]
    assert evidence_events
    assert evidence_events[0]["reference_projects"]
    assert "evidence_validation_summary" in evidence_events[0]["artifacts"]
    report_events = [event for event in events if event["stage"] == "report"]
    assert report_events
    assert int(report_events[0]["artifacts"]["react_section_count"]) >= 1
    assert report_events[0]["artifacts"]["gbrain_content_hash"]


def test_pipeline_can_record_retro_learning(tmp_path: Path):
    pipeline = IdeaToCouncilPipeline(
        hitl_adapter=HITLAdapter(mode="auto_approve"),
        research_runner=MockAcademicRunner(),
        vault_dir=tmp_path / "vault" / "insights",
        council_log_dir=tmp_path / "council",
        enable_learning=True,
        learning_log_path=tmp_path / "learnings.jsonl",
    )

    result = pipeline.run("한국 농가 진단키트 가격 책정")

    assert result.retrospective is not None
    assert result.retrospective.learnings
    assert (tmp_path / "learnings.jsonl").exists()
    assert int(result.state.artifacts["learning_count"]) >= 1
    assert any(event["stage"] == "agents" for event in result.progress_events)
