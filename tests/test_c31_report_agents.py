from src.evidence.artifact import EvidenceRef, Finding
from src.report.schema import ResearchReport
from src.report.composer import compose_research_report_markdown
from src.agents.generator import DebateAgentGenerator


def sample_report():
    ev = EvidenceRef(id="e1", source_url="https://example.com", source_title="Example", quote="quote", source_grade="A", provenance={"kind": "test"})
    finding = Finding(claim="Claim one", support=[ev], confidence=0.8, limitations=["limited sample"])
    return ResearchReport(brief_id="brief-1", title="Report", executive_summary="Summary", findings=[finding], evidence_refs=[ev], open_questions=["What next?"], confidence=0.7, limitations=["Early draft"])


def test_research_report_markdown_includes_evidence_and_limitations():
    markdown = compose_research_report_markdown(sample_report())
    assert "Claim one" in markdown
    assert "e1" in markdown
    assert "Early draft" in markdown


def test_debate_agent_generator_includes_mirofish_with_report_id():
    agents = DebateAgentGenerator().from_report(sample_report())
    names = {agent.name for agent in agents}
    assert "mirofish" in names
    assert {agent.source_report_id for agent in agents} == {"brief-1"}
    mirofish = next(agent for agent in agents if agent.name == "mirofish")
    assert "weak assumptions" in mirofish.system_prompt
    assert "missing evidence" in mirofish.system_prompt
