from src.pipeline.idea_to_council import IdeaToCouncilPipeline
from src.pipeline.stages import Stage


def test_idea_to_council_pipeline_runs_with_mocks():
    result = IdeaToCouncilPipeline().run("How should muchanipo turn reports into debate agents?")
    assert result.state.stage is Stage.DONE
    assert result.brief.is_ready
    assert result.report.findings
    assert any(agent.name == "mirofish" for agent in result.agents)
    assert result.council.rounds
