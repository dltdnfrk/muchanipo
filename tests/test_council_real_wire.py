from __future__ import annotations

from pathlib import Path

from src.agents.generator import DebateAgentGenerator, DebateAgentSpec
from src.agents.mirofish import debate_agent_to_council_persona
from src.council.session import CouncilSession
from src.execution.models import ModelResult
from src.report import compose_report
from src.report.schema import ResearchReport


class RecordingProvider:
    name = "recording"

    def __init__(self, response: str = "recorded critique") -> None:
        self.response = response
        self.prompts: list[str] = []

    def call(self, *, stage: str, prompt: str, **kwargs) -> ModelResult:
        self.prompts.append(prompt)
        return ModelResult(text=self.response, provider=self.name)


class RecordingGateway:
    def __init__(self, provider: RecordingProvider) -> None:
        self.provider = provider

    def call(self, *, stage: str, prompt: str, **kwargs) -> ModelResult:
        return self.provider.call(stage=stage, prompt=prompt, **kwargs)


def _agent(name: str = "mirofish") -> DebateAgentSpec:
    return DebateAgentSpec(
        name=name,
        role="critic",
        perspective="skeptical",
        expertise=["evidence"],
        challenge_targets=["claims"],
        source_report_id="report-1",
        system_prompt="find gaps",
    )


def test_session_round_uses_real_runner_prompt_with_layer_and_framework(tmp_path: Path):
    provider = RecordingProvider()
    session = CouncilSession(
        report_id="report-1",
        agents=[_agent()],
        topic="agtech market sizing",
        council_dir=tmp_path,
        max_rounds=10,
    )

    round_record = session.run_round(model_gateway=RecordingGateway(provider))

    assert round_record["responses"][0]["text"] == "recorded critique"
    assert "시장 규모 + 컨텍스트" in provider.prompts[0]
    assert "MECE Tree" in provider.prompts[0]
    assert "framework_output" in provider.prompts[0]
    assert (tmp_path / "round-1-mirofish.json").exists()


def test_session_round_n_uses_previous_results_in_cross_evaluation_prompt(tmp_path: Path):
    provider = RecordingProvider(response="follow-up critique")
    session = CouncilSession(
        report_id="report-1",
        agents=[_agent()],
        topic="agtech market sizing",
        council_dir=tmp_path,
        max_rounds=10,
    )

    session.run_round(model_gateway=RecordingGateway(provider))
    session.run_round(model_gateway=RecordingGateway(provider))

    assert "Round 2" in provider.prompts[-1]
    assert "follow-up critique" in provider.prompts[-1]
    assert "경쟁 지형" in provider.prompts[-1]


def test_session_detects_plateau_after_three_flat_rounds(tmp_path: Path):
    provider = RecordingProvider(response="same confidence critique")
    session = CouncilSession(
        report_id="report-1",
        agents=[_agent()],
        topic="plateau topic",
        council_dir=tmp_path,
        max_rounds=5,
    )
    gateway = RecordingGateway(provider)

    session.run_round(model_gateway=gateway)
    session.run_round(model_gateway=gateway)
    session.run_round(model_gateway=gateway)

    assert session.stopped is True
    assert session.stop_reason is not None
    assert "plateau detected" in session.stop_reason


def test_mirofish_adapter_matches_council_persona_schema():
    persona = debate_agent_to_council_persona(_agent())

    assert persona["name"] == "mirofish"
    assert persona["role"] == "critic"
    assert persona["expertise"] == ["evidence"]
    assert "perspective_bias" in persona
    assert "argument_style" in persona
    assert persona["agent_manifest"]["challenge_targets"] == ["claims"]


def test_generator_uses_council_personas_and_keeps_mirofish():
    report = ResearchReport(
        brief_id="report-1",
        title="Should agtech automate orchard scouting?",
        executive_summary="Evaluate adoption, evidence gaps, and implementation risks.",
        confidence=0.55,
        open_questions=["Which claims need field evidence?"],
    )

    agents = DebateAgentGenerator().from_report(
        report,
        target_count=4,
        research_type="analytical",
    )

    assert any(agent.name == "mirofish" for agent in agents)
    assert len(agents) >= 4
    assert all(agent.source_report_id == "report-1" for agent in agents)
    assert any("confidence" in agent.challenge_targets for agent in agents)


def test_council_session_outputs_can_compose_report_md(tmp_path: Path):
    provider = RecordingProvider(response="compose-ready critique")
    session = CouncilSession(
        report_id="report-1",
        agents=[_agent()],
        topic="compose report topic",
        council_dir=tmp_path,
        max_rounds=10,
    )

    session.run_round(model_gateway=RecordingGateway(provider))
    report_path = compose_report(tmp_path)

    assert report_path.name == "REPORT.md"
    assert report_path.exists()
    assert "compose-ready critique" in report_path.read_text(encoding="utf-8")
