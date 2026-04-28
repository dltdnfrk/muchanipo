from src.pipeline.idea_to_council import IdeaToCouncilPipeline
from src.pipeline.stages import Stage
from src.hitl.plannotator_adapter import HITLAdapter


def test_idea_to_council_pipeline_runs_with_mocks(tmp_path):
    result = IdeaToCouncilPipeline(
        hitl_adapter=HITLAdapter(mode="auto_approve"),
        vault_dir=tmp_path / "vault" / "insights",
        council_log_dir=tmp_path / "council",
    ).run("How should muchanipo turn reports into debate agents?")
    assert result.state.stage is Stage.DONE
    assert result.brief.is_ready
    assert result.report.findings
    assert any(agent.name == "mirofish" for agent in result.agents)
    assert result.council.rounds
