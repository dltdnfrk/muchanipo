#!/usr/bin/env python3
"""
MuchaNipo ReACT Report — Think→Act→Observe 루프 기반 보고서 (MiroFish 패턴)
Usage: python react-report.py <council-report.json> [--sections 3] [--output report.md]

Council 보고서를 읽고, 주제를 분석한 뒤, ReACT 루프 계획을 세워 마크다운 보고서를 생성한다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from typing import Any, List


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
