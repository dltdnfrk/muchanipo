from __future__ import annotations

import json

from conftest import load_script_module
from src.evidence.artifact import EvidenceRef


react_report = load_script_module("react_report_executor", "src/search/react-report.py")


def test_execute_react_section_calls_local_insight_and_mempalace_backends(tmp_path, monkeypatch):
    fixture = tmp_path / "insight.json"
    fixture.write_text(
        json.dumps(
            {
                "__default__": [
                    {
                        "text": "react backend evidence",
                        "source": "vault/react.md",
                        "score": 0.99,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("INSIGHT_FORGE_STUB_DATA", str(fixture))

    section = {
        "title": "Backend parity",
        "type": "finding",
        "source_text": "react backend evidence",
        "react": {
            "think": "collect backend evidence",
            "act": "insight-forge",
            "observe": "backend results",
            "write": "final answer",
        },
    }
    plan = react_report.run_react_loop_plan(
        section=section,
        report_title="ReACT parity",
        report_summary="summary",
        topic="react backend evidence",
        previous_sections=[],
    )

    result = react_report.execute_react_section(
        section=section,
        report={
            "topic": "react backend evidence",
            "evidence": [],
        },
        prompt_plan=plan,
        previous_sections=[],
    )

    observations = result["observations"]
    backend_tools = {
        item["tool"]
        for item in observations
        if item["executed_backend"]
    }
    assert {"insight_forge", "mempalace_search"}.issubset(backend_tools)
    assert "react backend evidence" in result["section_markdown"]
    assert result["execution_mode"] == "deterministic_tool_loop"


def test_execute_react_section_supports_llm_driven_react_loop(tmp_path, monkeypatch):
    fixture = tmp_path / "insight.json"
    fixture.write_text(
        json.dumps({"__default__": [{"text": "llm react evidence", "source": "vault/llm.md", "score": 0.9}]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("INSIGHT_FORGE_STUB_DATA", str(fixture))
    monkeypatch.setenv("MUCHANIPO_OFFLINE", "1")
    calls = [
        '<tool_call>{"name":"insight_forge","parameters":{"query":"llm react evidence"}}</tool_call>',
        '<tool_call>{"name":"mempalace_search","parameters":{"query":"llm react evidence"}}</tool_call>',
        '<tool_call>{"name":"web_search","parameters":{"query":"llm react evidence"}}</tool_call>',
        "Final Answer: LLM이 도구 관찰을 바탕으로 작성한 섹션입니다.",
    ]

    def responder(system_prompt, user_prompt, observations):
        assert "도구 호출 형식" in system_prompt
        assert "현재 작업" in user_prompt
        return calls.pop(0)

    result = react_report.execute_react_section(
        section={
            "title": "LLM ReACT",
            "type": "finding",
            "source_text": "llm react evidence",
        },
        report={
            "topic": "llm react evidence",
            "evidence": [{"source_url": "local", "quote": "llm react evidence", "source_title": "Local"}],
        },
        prompt_plan={
            "system_prompt": "도구 호출 형식",
            "user_prompt": "현재 작업",
            "react_config": {
                "available_tools": ["insight_forge", "mempalace_search", "web_search"],
                "min_tool_calls": 3,
                "max_tool_calls": 3,
                "max_iterations": 4,
            },
        },
        previous_sections=[],
        llm_responder=responder,
    )

    assert result["execution_mode"] == "llm_react_loop"
    assert result["llm_response_count"] == 4
    assert [call["name"] for call in result["tool_calls"]] == [
        "insight_forge",
        "mempalace_search",
        "web_search",
    ]
    assert result["section_markdown"] == "LLM이 도구 관찰을 바탕으로 작성한 섹션입니다."


def test_execute_react_section_wires_web_search_to_academic_backend(monkeypatch):
    monkeypatch.delenv("MUCHANIPO_OFFLINE", raising=False)

    def fake_academic_search(query: str, limit: int = 3):
        assert "live web evidence" in query
        assert limit == 3
        return [
            EvidenceRef(
                id="openalex:react",
                source_url="https://example.test/react",
                source_title="ReACT Academic Result",
                quote="live web evidence from academic backend",
                source_grade="A",
                provenance={"backend": "openalex"},
            )
        ]

    monkeypatch.setattr(react_report.academic_sync_search, "search", fake_academic_search)

    result = react_report.execute_react_section(
        section={
            "title": "Web backend",
            "type": "finding",
            "source_text": "live web evidence",
        },
        report={
            "topic": "live web evidence",
            "evidence": [],
        },
        prompt_plan={"react_config": {"available_tools": ["web_search"], "min_tool_calls": 1, "max_tool_calls": 1}},
        previous_sections=[],
    )

    assert result["observations"][0]["tool"] == "web_search"
    assert result["observations"][0]["executed_backend"] is True
    assert result["observations"][0]["fallback_reason"] == ""
    assert "live web evidence from academic backend" in result["section_markdown"]


def test_execute_react_section_keeps_web_search_offline(monkeypatch):
    monkeypatch.setenv("MUCHANIPO_OFFLINE", "1")

    def forbidden_search(*args, **kwargs):
        raise AssertionError("offline ReACT must not call academic web_search")

    monkeypatch.setattr(react_report.academic_sync_search, "search", forbidden_search)

    result = react_report.execute_react_section(
        section={"title": "Offline web", "type": "finding", "source_text": "offline evidence"},
        report={
            "topic": "offline evidence",
            "evidence": [{"source_url": "local", "quote": "offline fallback evidence", "source_title": "Local"}],
        },
        prompt_plan={"react_config": {"available_tools": ["web_search"], "min_tool_calls": 1, "max_tool_calls": 1}},
        previous_sections=[],
    )

    assert result["observations"][0]["executed_backend"] is False
    assert result["observations"][0]["fallback_reason"] == "backend_empty_or_unavailable"
    assert "offline fallback evidence" in result["section_markdown"]


def test_execute_react_section_logs_backend_failures(monkeypatch, caplog):
    monkeypatch.delenv("MUCHANIPO_OFFLINE", raising=False)

    def broken_search(*args, **kwargs):
        raise RuntimeError("academic unavailable")

    monkeypatch.setattr(react_report.academic_sync_search, "search", broken_search)

    result = react_report.execute_react_section(
        section={"title": "Web backend", "type": "finding", "source_text": "backend failure"},
        report={
            "topic": "backend failure",
            "evidence": [{"source_url": "local", "quote": "fallback evidence", "source_title": "Local"}],
        },
        prompt_plan={"react_config": {"available_tools": ["web_search"], "min_tool_calls": 1, "max_tool_calls": 1}},
        previous_sections=[],
    )

    assert result["observations"][0]["executed_backend"] is False
    assert result["observations"][0]["fallback_reason"] == "backend_empty_or_unavailable"
    assert "react web_search backend failed" in caplog.text
