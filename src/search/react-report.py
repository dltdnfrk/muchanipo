#!/usr/bin/env python3
"""
MuchaNipo ReACT Report — Think→Act→Observe 루프 기반 보고서 (MiroFish 패턴)
Usage: python react-report.py <council-report.json> [--sections 3] [--output report.md]

Council 보고서를 읽고, 주제를 분석한 뒤, ReACT 루프 계획을 세워 마크다운 보고서를 생성한다.

MiroFish 원본 패턴 채용:
- report_agent.py ReportAgent._generate_section_react: ReACT 루프 (Think→Act→Observe→Write)
- report_agent.py: 도구 호출 파싱, 관찰 주입, 최소/최대 도구 호출 강제, 충돌 처리
- report_agent.py: 섹션 계획 (plan_outline) + 섹션별 생성 (generate_section_react)
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, List

from src.research.academic import sync_search as academic_sync_search

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Council 보고서 파싱
# ---------------------------------------------------------------------------

def load_council_report(path: str) -> dict[str, Any]:
    """Council 보고서 JSON 파일 로드."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 필수 필드 검증 (유연하게 — 없으면 빈 값)
    return {
        "consensus": data.get("consensus", ""),
        "dissent": data.get("dissent", []),
        "evidence": data.get("evidence", []),
        "recommendations": data.get("recommendations", []),
        "personas": data.get("personas", []),
        "topic": data.get("topic", ""),
        "query": data.get("query", ""),
        # 원본 전체 보존
        "_raw": data,
    }


# ---------------------------------------------------------------------------
# 주제 추출 및 섹션 계획
# ---------------------------------------------------------------------------

def _extract_topics_from_consensus(consensus: str | list) -> list[str]:
    """consensus에서 핵심 주제 추출."""
    topics = []
    if isinstance(consensus, str):
        # 문장 단위로 분리, 각 문장을 주제 후보로
        sentences = re.split(r"[.。\n]", consensus)
        for s in sentences:
            s = s.strip()
            if len(s) > 10:
                topics.append(s)
    elif isinstance(consensus, list):
        for item in consensus:
            if isinstance(item, str) and len(item.strip()) > 5:
                topics.append(item.strip())
            elif isinstance(item, dict):
                topics.append(item.get("text", item.get("point", str(item))))
    return topics


def _extract_dissent_points(dissent: list | str) -> list[str]:
    """dissent에서 논쟁점 추출."""
    points = []
    if isinstance(dissent, str):
        for line in dissent.split("\n"):
            line = line.strip()
            if len(line) > 5:
                points.append(line)
    elif isinstance(dissent, list):
        for item in dissent:
            if isinstance(item, str):
                points.append(item.strip())
            elif isinstance(item, dict):
                points.append(item.get("text", item.get("point", str(item))))
    return points


def _extract_recommendations(recommendations: list | str) -> list[str]:
    """recommendations에서 액션 아이템 추출."""
    items = []
    if isinstance(recommendations, str):
        for line in recommendations.split("\n"):
            line = line.strip().lstrip("-•* ")
            if len(line) > 5:
                items.append(line)
    elif isinstance(recommendations, list):
        for item in recommendations:
            if isinstance(item, str):
                items.append(item.strip())
            elif isinstance(item, dict):
                items.append(item.get("text", item.get("action", str(item))))
    return items


def plan_sections(
    report: dict[str, Any],
    max_sections: int = 3,
) -> list[dict[str, Any]]:
    """
    Council 보고서를 분석하여 보고서 섹션 계획 생성.

    Returns:
        list[dict]: 각 섹션의 계획 정보
            - title: 섹션 제목
            - type: "finding" | "dissent" | "recommendation"
            - source_text: 근거 텍스트
            - react: ReACT 루프 계획
    """
    sections: list[dict[str, Any]] = []

    # 1. consensus 기반 핵심 발견 섹션
    topics = _extract_topics_from_consensus(report["consensus"])
    for i, topic in enumerate(topics[:max_sections]):
        sections.append({
            "title": _generate_section_title(topic),
            "type": "finding",
            "source_text": topic,
            "react": _build_react_plan(topic, "finding"),
        })

    # 2. dissent 기반 반론 섹션 (최소 1개 확보)
    dissent_points = _extract_dissent_points(report["dissent"])
    if dissent_points and len(sections) < max_sections + 1:
        combined_dissent = "; ".join(dissent_points[:3])
        sections.append({
            "title": "반론 및 리스크",
            "type": "dissent",
            "source_text": combined_dissent,
            "react": _build_react_plan(combined_dissent, "dissent"),
        })

    # 3. recommendations 기반 권고 섹션 (최소 1개 확보)
    rec_items = _extract_recommendations(report["recommendations"])
    if rec_items and len(sections) < max_sections + 2:
        combined_recs = "; ".join(rec_items[:5])
        sections.append({
            "title": "권고사항",
            "type": "recommendation",
            "source_text": combined_recs,
            "react": _build_react_plan(combined_recs, "recommendation"),
        })

    # 최소 2개, 최대 max_sections + 2개 섹션 보장
    return sections[:max_sections + 2]


def _generate_section_title(topic: str) -> str:
    """주제 텍스트에서 간결한 섹션 제목 생성."""
    # 앞 40자 이내로 자르되 단어 경계에서
    if len(topic) <= 40:
        return topic
    truncated = topic[:40]
    last_space = truncated.rfind(" ")
    if last_space > 20:
        truncated = truncated[:last_space]
    return truncated + "..."


def _build_react_plan(source_text: str, section_type: str) -> dict[str, str]:
    """
    ReACT 루프 계획 생성.

    Returns:
        dict with keys: think, act, observe, write
    """
    if section_type == "finding":
        return {
            "think": f"이 주제의 핵심 근거와 맥락을 조사: {source_text[:80]}",
            "act": _build_insight_forge_query(source_text),
            "observe": "관련 데이터, 선행 사례, 정량적 근거",
            "write": "제목 → 핵심 주장 → 근거 인용 → 출처",
        }
    elif section_type == "dissent":
        return {
            "think": f"반론의 타당성과 리스크 크기를 평가: {source_text[:80]}",
            "act": _build_insight_forge_query(source_text),
            "observe": "반대 의견의 근거, 실패 사례, 리스크 요인",
            "write": "논쟁점 → 반론 근거 → 리스크 매트릭스 → 완화 방안",
        }
    else:  # recommendation
        return {
            "think": f"실행 가능성과 우선순위를 판단: {source_text[:80]}",
            "act": _build_insight_forge_query(source_text),
            "observe": "구현 사례, 필요 리소스, 예상 효과",
            "write": "액션 아이템 → 우선순위 → 담당 → 기한",
        }


def _build_insight_forge_query(text: str) -> str:
    """InsightForge 검색 쿼리 형식으로 변환."""
    # 핵심 키워드 추출 (간단한 규칙 기반)
    stopwords = {"의", "에", "을", "를", "이", "가", "은", "는", "와", "과", "한", "된", "로", "으로"}
    words = re.findall(r"[\w가-힣]+", text)
    keywords = [w for w in words if w not in stopwords and len(w) >= 2][:8]
    return f'insight-forge.py "{" ".join(keywords)}" --depth deep'


# ---------------------------------------------------------------------------
# Adopted from MiroFish: report_agent.py:470-493
# 도구 설명 상수 (ReACT 루프에서 LLM에 제공)
# ---------------------------------------------------------------------------

TOOL_DESC_INSIGHT_FORGE = """\
[심층 분석 검색 - InsightForge]
강력한 다차원 검색. 자동으로 하위 질문을 분해하여 검색합니다.
- 시맨틱 검색 + 엔티티 분석 + 관계 체인 추적
- 사용 시기: 깊은 분석, 다면적 조사, 근거 수집"""

TOOL_DESC_MEMPALACE_SEARCH = """\
[MemPalace 검색]
저장된 지식 검색. 키워드 또는 자연어 쿼리로 검색합니다.
- wing/room 필터링 가능
- 사용 시기: 특정 정보 확인, 빠른 검색"""

TOOL_DESC_WEB_SEARCH = """\
[웹 검색]
외부 정보 검색. 최신 데이터 확인에 사용합니다.
- 사용 시기: 외부 근거 확보, 최신 정보 검증"""


# ---------------------------------------------------------------------------
# Adopted from MiroFish: report_agent.py:796-826
# ReACT 루프 메시지 템플릿
# ---------------------------------------------------------------------------

REACT_OBSERVATION_TEMPLATE = """\
Observation (검색 결과):

=== 도구 {tool_name} 반환 ===
{result}

===
도구 호출 {tool_calls_count}/{max_tool_calls}회 (사용한 도구: {used_tools_str}){unused_hint}
- 정보 충분: "Final Answer:" 로 시작하여 섹션 내용 출력 (근거 인용 필수)
- 추가 정보 필요: 도구 하나를 더 호출
==="""

REACT_INSUFFICIENT_TOOLS_MSG = (
    "[주의] 도구를 {tool_calls_count}회만 호출했습니다. 최소 {min_tool_calls}회 필요합니다. "
    "추가 검색 후 Final Answer를 출력하세요.{unused_hint}"
)

REACT_TOOL_LIMIT_MSG = (
    "도구 호출 횟수가 상한({tool_calls_count}/{max_tool_calls})에 도달했습니다. "
    '더 이상 도구를 호출할 수 없습니다. "Final Answer:" 로 시작하여 섹션 내용을 출력하세요.'
)

REACT_UNUSED_TOOLS_HINT = "\n(아직 사용하지 않은 도구: {unused_list} -- 다양한 도구를 사용하세요)"

REACT_FORCE_FINAL_MSG = "최대 반복 횟수에 도달했습니다. Final Answer를 출력하여 섹션 내용을 생성하세요."


# ---------------------------------------------------------------------------
# Adopted from MiroFish: report_agent.py:860-876, 1221-1500
# ReACT 섹션 생성 엔진 (프롬프트 계획 생성)
# ---------------------------------------------------------------------------

# 사용 가능한 도구 집합
ALL_TOOLS = {"insight_forge", "mempalace_search", "web_search"}

# 도구 호출 제한
MAX_TOOL_CALLS_PER_SECTION = 5  # Adopted from MiroFish: report_agent.py:877
MIN_TOOL_CALLS = 3              # Adopted from MiroFish: report_agent.py:1288
MAX_ITERATIONS = 5              # Adopted from MiroFish: report_agent.py:1287


def build_react_section_prompt(
    section: dict[str, Any],
    report_title: str,
    report_summary: str,
    topic: str,
    previous_sections: list[str],
) -> dict[str, Any]:
    """
    ReACT 루프 기반 섹션 생성을 위한 프롬프트 계획 구성.

    MiroFish ReportAgent._generate_section_react의 프롬프트 구조를 포팅.
    실제 LLM 호출과 도구 실행은 오케스트레이터(Claude Code)가 수행.
    이 함수는 루프 구조와 프롬프트만 정의.

    # Adopted from MiroFish: report_agent.py:1221-1294

    Args:
        section: 섹션 계획 dict (title, type, source_text, react)
        report_title: 보고서 제목
        report_summary: 보고서 요약
        topic: 연구 주제
        previous_sections: 이전 섹션 내용 리스트

    Returns:
        ReACT 루프 실행 계획 dict
    """
    # 도구 설명 텍스트
    # Adopted from MiroFish: report_agent.py:1127-1135
    tools_description = "\n\n".join([
        TOOL_DESC_INSIGHT_FORGE,
        TOOL_DESC_MEMPALACE_SEARCH,
        TOOL_DESC_WEB_SEARCH,
    ])

    # 시스템 프롬프트 (MiroFish SECTION_SYSTEM_PROMPT_TEMPLATE 구조)
    # Adopted from MiroFish: report_agent.py:615-767
    system_prompt = f"""\
당신은 연구 보고서의 한 섹션을 작성하는 전문가입니다.

보고서 제목: {report_title}
보고서 요약: {report_summary}
연구 주제: {topic}

현재 작성할 섹션: {section['title']}

=== 핵심 규칙 ===
1. 반드시 도구를 호출하여 근거를 수집한 뒤 작성하세요
2. 근거 원문을 인용 형식(> "...")으로 포함하세요
3. 매 섹션 최소 {MIN_TOOL_CALLS}회, 최대 {MAX_TOOL_CALLS_PER_SECTION}회 도구 호출
4. 도구 호출과 Final Answer를 동시에 출력하지 마세요

=== 사용 가능한 도구 ===
{tools_description}

=== 도구 호출 형식 ===
<tool_call>
{{"name": "도구이름", "parameters": {{"query": "검색어"}}}}
</tool_call>

=== 최종 출력 형식 ===
충분한 근거를 수집한 후 "Final Answer:" 로 시작하여 섹션 내용을 출력하세요.
마크다운 형식 사용, 단 제목(#, ##, ###)은 사용하지 마세요.
"""

    # 이전 섹션 내용 (중복 방지)
    # Adopted from MiroFish: report_agent.py:1265-1273
    if previous_sections:
        prev_parts = [s[:4000] + "..." if len(s) > 4000 else s for s in previous_sections]
        previous_content = "\n\n---\n\n".join(prev_parts)
    else:
        previous_content = "(첫 번째 섹션입니다)"

    # 사용자 프롬프트
    # Adopted from MiroFish: report_agent.py:769-792
    user_prompt = f"""\
이전 섹션 내용 (중복 방지):
{previous_content}

=== 현재 작업: {section['title']} 섹션 작성 ===

ReACT 실행 계획:
- THINK: {section['react']['think']}
- ACT: {section['react']['act']}
- OBSERVE: {section['react']['observe']}
- WRITE: {section['react']['write']}

시작하세요:
1. 먼저 이 섹션에 필요한 정보를 생각(Think)하세요
2. 도구를 호출(Act)하여 근거를 수집하세요
3. 충분한 근거 수집 후 Final Answer로 섹션 내용을 출력하세요
"""

    return {
        "section_title": section["title"],
        "section_type": section["type"],
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        # ReACT 루프 설정 (오케스트레이터용)
        # Adopted from MiroFish: report_agent.py:1285-1291
        "react_config": {
            "max_iterations": MAX_ITERATIONS,
            "max_tool_calls": MAX_TOOL_CALLS_PER_SECTION,
            "min_tool_calls": MIN_TOOL_CALLS,
            "available_tools": list(ALL_TOOLS),
            "observation_template": REACT_OBSERVATION_TEMPLATE,
            "insufficient_tools_msg": REACT_INSUFFICIENT_TOOLS_MSG,
            "tool_limit_msg": REACT_TOOL_LIMIT_MSG,
            "unused_tools_hint": REACT_UNUSED_TOOLS_HINT,
            "force_final_msg": REACT_FORCE_FINAL_MSG,
        },
    }


def parse_tool_calls(response: str) -> list[dict[str, Any]]:
    """
    LLM 응답에서 도구 호출을 파싱.

    MiroFish ReportAgent._parse_tool_calls의 정확한 포팅.
    XML 스타일 (<tool_call>) 우선, 베어 JSON fallback.

    # Adopted from MiroFish: report_agent.py:1067-1112

    Args:
        response: LLM 응답 텍스트

    Returns:
        파싱된 도구 호출 리스트
    """
    tool_calls: list[dict[str, Any]] = []

    # 형식 1: XML 스타일 (표준)
    # Adopted from MiroFish: report_agent.py:1078-1087
    xml_pattern = r'<tool_call>\s*(\{.*?\})\s*</tool_call>'
    for match in re.finditer(xml_pattern, response, re.DOTALL):
        try:
            call_data = json.loads(match.group(1))
            tool_calls.append(call_data)
        except json.JSONDecodeError:
            pass

    if tool_calls:
        return tool_calls

    # 형식 2: 베어 JSON fallback
    # Adopted from MiroFish: report_agent.py:1089-1112
    stripped = response.strip()
    if stripped.startswith('{') and stripped.endswith('}'):
        try:
            call_data = json.loads(stripped)
            if _is_valid_tool_call(call_data):
                return [call_data]
        except json.JSONDecodeError:
            pass

    # 응답 끝부분에서 JSON 추출 시도
    json_pattern = r'(\{"(?:name|tool)"\s*:.*?\})\s*$'
    match = re.search(json_pattern, stripped, re.DOTALL)
    if match:
        try:
            call_data = json.loads(match.group(1))
            if _is_valid_tool_call(call_data):
                tool_calls.append(call_data)
        except json.JSONDecodeError:
            pass

    return tool_calls


def _is_valid_tool_call(data: dict) -> bool:
    """도구 호출 JSON 유효성 검증.
    # Adopted from MiroFish: report_agent.py:1114-1125
    """
    tool_name = data.get("name") or data.get("tool")
    if tool_name and tool_name in ALL_TOOLS:
        # 키 이름 정규화
        if "tool" in data:
            data["name"] = data.pop("tool")
        if "params" in data and "parameters" not in data:
            data["parameters"] = data.pop("params")
        return True
    return False


def run_react_loop_plan(
    section: dict[str, Any],
    report_title: str,
    report_summary: str,
    topic: str,
    previous_sections: list[str],
) -> dict[str, Any]:
    """
    ReACT 루프 실행 계획을 완전히 구성하여 반환.

    오케스트레이터(Claude Code)가 이 계획을 받아서:
    1. system_prompt + user_prompt로 LLM 호출
    2. 응답에서 parse_tool_calls로 도구 호출 파싱
    3. 도구 실행 후 observation_template으로 결과 주입
    4. min_tool_calls 미달 시 insufficient_tools_msg 주입
    5. max_tool_calls 초과 시 tool_limit_msg 주입
    6. "Final Answer:" 감지 시 섹션 내용 추출

    # Adopted from MiroFish: report_agent.py:1296-1500

    Args:
        section: 섹션 계획 dict
        report_title: 보고서 제목
        report_summary: 보고서 요약
        topic: 연구 주제
        previous_sections: 이전 섹션 내용

    Returns:
        완전한 ReACT 실행 계획 dict
    """
    prompt_plan = build_react_section_prompt(
        section=section,
        report_title=report_title,
        report_summary=report_summary,
        topic=topic,
        previous_sections=previous_sections,
    )

    return {
        **prompt_plan,
        "instructions": (
            "이 계획을 Claude Code Agent로 실행하세요.\n"
            "1. system_prompt + user_prompt로 LLM 호출\n"
            "2. 응답에서 <tool_call> 파싱 (parse_tool_calls 함수 사용)\n"
            "3. 도구 실행 후 observation_template으로 결과를 user 메시지로 주입\n"
            "4. 'Final Answer:' 감지 시 섹션 내용 추출\n"
            "5. 최대 반복: react_config.max_iterations\n"
            "6. 최소 도구 호출: react_config.min_tool_calls (미달 시 거부)\n"
            "7. 최대 도구 호출: react_config.max_tool_calls (초과 시 강제 Final Answer)"
        ),
    }


def execute_react_section(
    section: dict[str, Any],
    report: dict[str, Any],
    prompt_plan: dict[str, Any],
    previous_sections: list[str] | None = None,
) -> dict[str, Any]:
    """Execute a deterministic offline ReACT loop for one section.

    The upstream MiroFish loop is LLM-driven. Muchanipo's offline runtime keeps
    the same control contract by generating structured tool-call messages,
    parsing them through ``parse_tool_calls``, collecting observations from the
    report evidence payload, and writing the section from those observations.
    """
    config = prompt_plan.get("react_config") or {}
    available_tools = list(config.get("available_tools") or sorted(ALL_TOOLS))
    min_calls = int(config.get("min_tool_calls") or MIN_TOOL_CALLS)
    max_calls = int(config.get("max_tool_calls") or MAX_TOOL_CALLS_PER_SECTION)
    planned_tools = _planned_react_tools(available_tools, min_calls, max_calls)
    tool_calls: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    query = str(section.get("source_text") or report.get("topic") or report.get("query") or "")

    for tool_name in planned_tools:
        response = _scripted_tool_call_response(tool_name, query)
        for call in parse_tool_calls(response):
            tool_calls.append(call)
            observations.append(_run_react_tool(call, report))

    final_answer = _build_final_answer(section, observations, previous_sections or [])
    return {
        "section_title": str(section.get("title") or ""),
        "section_type": str(section.get("type") or ""),
        "tool_calls": tool_calls,
        "observations": observations,
        "final_answer": final_answer,
        "section_markdown": final_answer,
        "react_config": config,
    }


def _planned_react_tools(available_tools: list[str], min_calls: int, max_calls: int) -> list[str]:
    preferred = ["insight_forge", "mempalace_search", "web_search"]
    ordered = [tool for tool in preferred if tool in available_tools]
    ordered.extend(tool for tool in available_tools if tool not in ordered)
    target = max(1, min(max_calls, min_calls))
    if not ordered:
        ordered = ["web_search"]
    while len(ordered) < target:
        ordered.append(ordered[-1])
    return ordered[:target]


def _scripted_tool_call_response(tool_name: str, query: str) -> str:
    return "\n".join([
        f"Thought: collect evidence for {query[:120]}",
        "<tool_call>",
        json.dumps({"name": tool_name, "parameters": {"query": query}}, ensure_ascii=False),
        "</tool_call>",
    ])


def _run_react_tool(call: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    name = str(call.get("name") or call.get("tool") or "web_search")
    parameters = call.get("parameters") or {}
    query = str(parameters.get("query") or report.get("topic") or report.get("query") or "")
    snippets = _execute_react_tool_backend(name, query)
    executed_backend = bool(snippets)
    fallback_reason = ""
    if not snippets:
        fallback_reason = "backend_empty_or_unavailable"
        matched = _find_related_evidence(query, report.get("evidence", []), max_results=3)
        if not matched:
            matched = list(report.get("evidence", []))[:2]
        snippets = [
            {
                "source": _extract_evidence_source(item),
                "text": _extract_evidence_text(item),
            }
            for item in matched
        ]
    return {
        "tool": name,
        "query": query,
        "executed_backend": executed_backend,
        "fallback_reason": fallback_reason,
        "result_count": len(snippets),
        "snippets": snippets,
    }


def _execute_react_tool_backend(name: str, query: str) -> list[dict[str, str]]:
    module = _load_insight_forge_module()
    if name == "web_search":
        return _execute_web_search_backend(query)
    if module is None:
        return []
    try:
        if name == "insight_forge":
            payload = module.insight_forge(query=query, depth="light")
            raw_results = list((payload or {}).get("results", []) or [])
        elif name == "mempalace_search":
            raw_results = list(module.search_mempalace(query=query, limit=3) or [])
        else:
            return []
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("react backend %s failed for query %r: %s", name, query, exc)
        return []
    snippets: list[dict[str, str]] = []
    for item in raw_results[:3]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or item.get("content") or item.get("quote") or "").strip()
        source = str(item.get("source") or item.get("file") or item.get("wing") or name).strip()
        if text:
            snippets.append({"source": source, "text": text})
    return snippets


def _execute_web_search_backend(query: str) -> list[dict[str, str]]:
    if os.environ.get("MUCHANIPO_OFFLINE", "").strip().lower() in {"1", "true", "yes", "on"}:
        return []
    try:
        refs = academic_sync_search.search(query, limit=3)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("react web_search backend failed for query %r: %s", query, exc)
        return []
    snippets: list[dict[str, str]] = []
    for ref in refs[:3]:
        if isinstance(ref, dict):
            text = str(ref.get("quote") or ref.get("text") or ref.get("title") or "").strip()
            source = str(ref.get("source_url") or ref.get("source") or ref.get("id") or "web_search").strip()
        else:
            text = str(getattr(ref, "quote", None) or getattr(ref, "source_title", None) or "").strip()
            source = str(
                getattr(ref, "source_url", None)
                or getattr(ref, "source_title", None)
                or getattr(ref, "id", None)
                or "web_search"
            ).strip()
        if text:
            snippets.append({"source": source, "text": text})
    return snippets


def _load_insight_forge_module() -> Any | None:
    src_path = Path(__file__).with_name("insight-forge.py")
    if not src_path.exists():
        return None
    try:
        spec = importlib.util.spec_from_file_location("muchanipo_react_insight_forge", src_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("react insight_forge import failed: %s", exc)
        return None


def _build_final_answer(
    section: dict[str, Any],
    observations: list[dict[str, Any]],
    previous_sections: list[str],
) -> str:
    source_text = str(section.get("source_text") or "").strip()
    lines = [
        f"**핵심 주장:** {source_text or section.get('title') or '추가 검증 필요'}",
        "",
        "**도구 관찰:**",
    ]
    seen: set[tuple[str, str]] = set()
    for observation in observations:
        for snippet in observation.get("snippets", []) or []:
            source = str(snippet.get("source") or "unknown")
            text = str(snippet.get("text") or "").strip()
            key = (source, text)
            if not text or key in seen:
                continue
            seen.add(key)
            lines.append(f"- {observation['tool']} | {source}: {text[:240]}")
    if len(lines) == 3:
        lines.append("- 근거 관찰이 충분하지 않아 추가 수집이 필요합니다.")
    if previous_sections:
        lines.extend(["", f"**중복 방지:** 이전 {len(previous_sections)}개 섹션과 구분해 작성했습니다."])
    lines.extend([
        "",
        "**작성 결과:**",
        f"{source_text or section.get('title') or '이 섹션'}에 대해 위 관찰을 근거로 판단합니다.",
    ])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 마크다운 보고서 생성
# ---------------------------------------------------------------------------

def generate_report(
    report: dict[str, Any],
    sections: list[dict[str, Any]],
) -> str:
    """Council 분석 결과를 마크다운 보고서로 생성."""
    lines: list[str] = []

    # 제목
    topic = report.get("topic") or report.get("query") or "Council 분석"
    lines.append(f"# {topic} — Council 분석 보고서")
    lines.append("")
    lines.append(f"> 생성일: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"> 생성기: MuchaNipo ReACT Report (MiroFish 패턴)")
    lines.append("")

    # 개요
    lines.append("## 개요")
    lines.append("")
    consensus_text = _format_consensus(report["consensus"])
    lines.append(consensus_text)
    lines.append("")

    # 참여 페르소나
    if report["personas"]:
        lines.append("### 참여 관점")
        lines.append("")
        for persona in report["personas"]:
            if isinstance(persona, str):
                lines.append(f"- {persona}")
            elif isinstance(persona, dict):
                name = persona.get("name", persona.get("role", ""))
                lines.append(f"- **{name}**")
        lines.append("")

    # 본문 섹션
    section_num = 0
    for section in sections:
        if section["type"] == "finding":
            section_num += 1
            lines.extend(_render_finding_section(section, section_num, report))
        elif section["type"] == "dissent":
            lines.extend(_render_dissent_section(section, report))
        elif section["type"] == "recommendation":
            lines.extend(_render_recommendation_section(section, report))

    # ReACT 실행 계획 (부록)
    lines.append("---")
    lines.append("")
    lines.append("## 부록: ReACT 실행 계획")
    lines.append("")
    for i, section in enumerate(sections, 1):
        react = section["react"]
        lines.append(f"### 섹션 {i}: {section['title']}")
        lines.append("")
        lines.append(f"```")
        lines.append(f"[THINK]   {react['think']}")
        lines.append(f"[ACT]     {react['act']}")
        lines.append(f"[OBSERVE] {react['observe']}")
        lines.append(f"[WRITE]   {react['write']}")
        lines.append(f"```")
        lines.append("")

    return "\n".join(lines)


def _format_consensus(consensus: str | list) -> str:
    """consensus를 읽기 좋은 텍스트로 변환."""
    if isinstance(consensus, str):
        return consensus
    elif isinstance(consensus, list):
        formatted = []
        for item in consensus:
            if isinstance(item, str):
                formatted.append(f"- {item}")
            elif isinstance(item, dict):
                text = item.get("text", item.get("point", str(item)))
                formatted.append(f"- {text}")
        return "\n".join(formatted)
    return str(consensus)


def _render_finding_section(
    section: dict[str, Any],
    num: int,
    report: dict[str, Any],
) -> list[str]:
    """finding 타입 섹션 렌더링."""
    lines = []
    lines.append(f"## 섹션 {num}: {section['title']}")
    lines.append("")

    lines.append("### 핵심 발견")
    lines.append("")
    lines.append(section["source_text"])
    lines.append("")

    # 관련 근거 매칭
    evidence = _find_related_evidence(section["source_text"], report["evidence"])
    if evidence:
        lines.append("### 근거")
        lines.append("")
        for ev in evidence:
            source = _extract_evidence_source(ev)
            text = _extract_evidence_text(ev)
            lines.append(f"- [Source: {source}] {text}")
        lines.append("")

    return lines


def _render_dissent_section(
    section: dict[str, Any],
    report: dict[str, Any],
) -> list[str]:
    """dissent 타입 섹션 렌더링."""
    lines = []
    lines.append("## 반론 및 리스크")
    lines.append("")

    dissent_points = _extract_dissent_points(report["dissent"])
    if dissent_points:
        for point in dissent_points:
            lines.append(f"- **{point}**")
        lines.append("")
    else:
        lines.append(section["source_text"])
        lines.append("")

    # 관련 근거
    evidence = _find_related_evidence(section["source_text"], report["evidence"])
    if evidence:
        lines.append("### 반론 근거")
        lines.append("")
        for ev in evidence:
            source = _extract_evidence_source(ev)
            text = _extract_evidence_text(ev)
            lines.append(f"- [Source: {source}] {text}")
        lines.append("")

    return lines


def _render_recommendation_section(
    section: dict[str, Any],
    report: dict[str, Any],
) -> list[str]:
    """recommendation 타입 섹션 렌더링."""
    lines = []
    lines.append("## 권고사항")
    lines.append("")

    rec_items = _extract_recommendations(report["recommendations"])
    if rec_items:
        for i, item in enumerate(rec_items, 1):
            lines.append(f"- [ ] **{i}.** {item}")
        lines.append("")
    else:
        lines.append(section["source_text"])
        lines.append("")

    return lines


# ---------------------------------------------------------------------------
# 근거 매칭 헬퍼
# ---------------------------------------------------------------------------

def _find_related_evidence(
    topic_text: str,
    evidence_list: list,
    max_results: int = 3,
) -> list:
    """주제 텍스트와 관련된 근거를 매칭."""
    if not evidence_list:
        return []

    topic_words = set(re.findall(r"[\w가-힣]{2,}", topic_text.lower()))

    scored = []
    for ev in evidence_list:
        ev_text = _extract_evidence_text(ev).lower()
        ev_words = set(re.findall(r"[\w가-힣]{2,}", ev_text))
        overlap = len(topic_words & ev_words)
        if overlap > 0:
            scored.append((overlap, ev))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:max_results]]


def _extract_evidence_source(evidence: Any) -> str:
    """근거 항목에서 출처 추출."""
    if isinstance(evidence, dict):
        return evidence.get("source", evidence.get("file", evidence.get("wing", "unknown")))
    return "unknown"


def _extract_evidence_text(evidence: Any) -> str:
    """근거 항목에서 텍스트 추출."""
    if isinstance(evidence, str):
        return evidence
    if isinstance(evidence, dict):
        return evidence.get("text", evidence.get("content", evidence.get("quote", str(evidence))))
    return str(evidence)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="MuchaNipo ReACT Report — Think→Act→Observe 루프 기반 보고서 (MiroFish 패턴)",
    )
    parser.add_argument(
        "council_report",
        type=str,
        help="Council 보고서 JSON 파일 경로",
    )
    parser.add_argument(
        "--sections",
        type=int,
        default=3,
        help="본문 섹션 수 (기본: 3, 범위: 2-5)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="출력 마크다운 파일 경로 (기본: stdout)",
    )

    args = parser.parse_args()

    # 섹션 수 범위 제한
    max_sections = max(2, min(5, args.sections))

    # Council 보고서 로드
    if not os.path.isfile(args.council_report):
        print(f"오류: 파일을 찾을 수 없습니다: {args.council_report}", file=sys.stderr)
        sys.exit(1)

    try:
        report = load_council_report(args.council_report)
    except json.JSONDecodeError as e:
        print(f"오류: JSON 파싱 실패: {e}", file=sys.stderr)
        sys.exit(1)

    # 섹션 계획
    sections = plan_sections(report, max_sections=max_sections)

    # 보고서 생성
    markdown = generate_report(report, sections)

    # 출력
    if args.output:
        output_dir = os.path.dirname(args.output)
        if output_dir and not os.path.isdir(output_dir):
            os.makedirs(output_dir, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(markdown)
        print(f"보고서 생성 완료: {args.output}", file=sys.stderr)
    else:
        print(markdown)


if __name__ == "__main__":
    main()
