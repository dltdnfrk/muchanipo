from __future__ import annotations

from pathlib import Path

RUN_PROGRESS = Path("app/muchanipo-tauri/src/pages/RunProgress.tsx")


def test_autostart_interview_does_not_use_stale_hardcoded_topic() -> None:
    source = RUN_PROGRESS.read_text(encoding="utf-8")
    assert "농업 온톨로지 데이터 추출 기반 대사체 농업" not in source
    assert "대사체 농업 적용 사례" not in source


def test_autostart_interview_q1_is_scoped_to_current_run_topic() -> None:
    source = RUN_PROGRESS.read_text(encoding="utf-8")
    assert "const currentRunTopic =" in source
    assert "localStorage.getItem(`run:${runId}:topic`)" in source
    assert "interviewPrompt.id === \"Q1_research_question\"" in source
    assert "interviewPrompt.id === \"Q1\"" not in source
    assert "? currentRunTopic" in source
