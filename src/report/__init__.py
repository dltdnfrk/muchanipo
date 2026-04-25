"""Report Composer (C26) — Council 결과를 MBB-급 30+ p markdown으로 합성.

LLM 호출 없이 stdlib only. 페르소나가 이미 framework_output을 채웠으니
composer는 조립·정리·SCR 구조화만 담당.

산출: council-logs/{council_id}/REPORT.md
"""
from __future__ import annotations

from .composer import ReportComposer, compose_report

__all__ = ["ReportComposer", "compose_report"]
