from src.pipeline.stages import Stage
from src.pipeline.state import PipelineState


def test_pipeline_state_defaults_to_idea_dump():
    state = PipelineState(run_id="run-1")
    assert state.stage is Stage.IDEA_DUMP
    assert state.artifacts == {}


def test_pipeline_state_advance_and_artifacts():
    state = PipelineState(run_id="run-1")
    state.record_artifact("brief_id", "brief-1")
    state.advance(Stage.INTERVIEW)
    assert state.stage is Stage.INTERVIEW
    assert state.artifacts["brief_id"] == "brief-1"
