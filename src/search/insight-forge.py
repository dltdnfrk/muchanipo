#!/usr/bin/env python3
"""
MuchaNipo InsightForge — 다차원 검색 엔진 (MiroFish 패턴)
Usage: python insight-forge.py "query" [--depth deep|light] [--output json|text]

쿼리를 하위 질문으로 자동 분해 → 각각 검색 → RRF로 통합.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# MemPalace 검색 stub
# ---------------------------------------------------------------------------

def search_mempalace(query: str, wing: str = None, room: str = None, limit: int = 5) -> list[dict]:
    """
    MemPalace 검색 stub.
    실제 사용 시: Claude Code에서 mcp__mempalace__mempalace_search 호출로 대체.
    muchanipo.md 오케스트레이터가 이 함수 대신 실제 MCP 도구를 호출함.

    Returns:
        list[dict]: 각 항목은 {"text": str, "source": str, "score": float}
    """
    # TODO: 실제 MemPalace MCP 연동 시 이 함수를 교체
    return []


# ---------------------------------------------------------------------------
# 5W1H 하위 질문 분해
# ---------------------------------------------------------------------------

# 한국어 키워드 → 5W1H 차원 매핑
_KO_PATTERNS: dict[str, str] = {
    "누가": "WHO",
    "누구": "WHO",
    "인물": "WHO",
    "조직": "WHO",
    "팀": "WHO",
    "무엇": "WHAT",
    "제품": "WHAT",
    "기술": "WHAT",
    "기능": "WHAT",
    "어떻게": "HOW",
    "방법": "HOW",
    "프로세스": "HOW",
    "구현": "HOW",
    "왜": "WHY",
    "이유": "WHY",
    "배경": "WHY",
    "문제": "WHY",
    "동기": "WHY",
    "언제": "WHEN",
    "일정": "WHEN",
    "시기": "WHEN",
    "기한": "WHEN",
    "날짜": "WHEN",
}

# 5W1H 질문 템플릿
_QUESTION_TEMPLATES: dict[str, str] = {
    "WHO": "관련 인물/조직은?",
    "WHAT": "핵심 기술/제품은?",
    "HOW": "구현 방법/프로세스는?",
    "WHY": "동기/배경/문제점은?",
    "WHEN": "시간적 맥락/일정은?",
}

# 5W1H 차원 우선순위 (기본)
_DEFAULT_PRIORITY = ["WHAT", "WHY", "HOW", "WHO", "WHEN"]


def _detect_dimensions(query: str) -> list[str]:
    """쿼리에서 한국어 키워드를 인식해 관련 5W1H 차원을 우선 배치."""
    detected: list[str] = []
    for keyword, dimension in _KO_PATTERNS.items():
        if keyword in query and dimension not in detected:
            detected.append(dimension)
    return detected


def decompose_query(query: str, max_questions: int = 5) -> list[dict[str, str]]:
    """
    쿼리를 5W1H 프레임워크 기반 하위 질문으로 분해.

    Returns:
        list[dict]: [{"dimension": "WHO", "question": "...에 관련된 인물/조직은?"}]
    """
    detected = _detect_dimensions(query)

    # 감지된 차원 우선, 나머지는 기본 순서로
    ordered = detected[:]
    for dim in _DEFAULT_PRIORITY:
        if dim not in ordered:
            ordered.append(dim)

    ordered = ordered[:max_questions]

    sub_questions = []
    for dim in ordered:
        template = _QUESTION_TEMPLATES[dim]
        question = f"{query}에 대해 — {template}"
        sub_questions.append({"dimension": dim, "question": question})

    return sub_questions


# ---------------------------------------------------------------------------
# 검색 쿼리 생성 (불용어 제거 + 키워드 추출)
# ---------------------------------------------------------------------------

_STOPWORDS_KO = frozenset([
    "은", "는", "이", "가", "을", "를", "의", "에", "에서", "로", "으로",
    "와", "과", "도", "만", "까지", "부터", "에게", "한테", "께",
    "그", "이", "저", "것", "수", "등", "및", "또는", "그리고",
    "하다", "되다", "있다", "없다", "아니다",
    "대해", "관련", "대한", "위한", "통해",
])

_STOPWORDS_EN = frozenset([
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "can", "shall",
    "in", "on", "at", "to", "for", "of", "with", "by", "from",
    "and", "or", "but", "not", "no", "if", "then", "so",
    "this", "that", "these", "those", "it", "its",
    "about", "what", "how", "why", "when", "who", "which", "where",
])


def extract_keywords(text: str) -> list[str]:
    """텍스트에서 불용어를 제거하고 핵심 키워드를 추출."""
    # 구두점 제거, 소문자화
    cleaned = re.sub(r"[^\w\s가-힣]", " ", text)
    tokens = cleaned.split()

    keywords = []
    for token in tokens:
        lower = token.lower()
        if lower in _STOPWORDS_KO or lower in _STOPWORDS_EN:
            continue
        if len(token) < 2:
            continue
        if token not in keywords:
            keywords.append(token)

    return keywords


def build_search_queries(sub_questions: list[dict[str, str]]) -> list[dict[str, Any]]:
    """하위 질문들을 MemPalace 검색 쿼리로 변환."""
    queries = []
    for sq in sub_questions:
        keywords = extract_keywords(sq["question"])
        query_str = " ".join(keywords[:6])  # 최대 6개 키워드
        queries.append({
            "dimension": sq["dimension"],
            "query": query_str,
            "keywords": keywords[:6],
        })
    return queries


# ---------------------------------------------------------------------------
# RRF (Reciprocal Rank Fusion) 통합
# ---------------------------------------------------------------------------

_RRF_K = 60  # RRF 상수


def reciprocal_rank_fusion(
    ranked_lists: list[list[dict]],
    dimensions: list[str],
) -> list[dict]:
    """
    여러 랭킹 리스트를 RRF로 통합.

    RRF_score(d) = Σ 1/(k + rank_i(d))  for each query i

    Args:
        ranked_lists: 각 검색 쿼리의 결과 리스트 (순위순 정렬)
        dimensions: 각 리스트에 대응하는 5W1H 차원

    Returns:
        RRF 스코어 기준 정렬된 통합 결과
    """
    scores: dict[str, float] = defaultdict(float)
    items: dict[str, dict] = {}
    matched: dict[str, list[str]] = defaultdict(list)

    for dim, ranked in zip(dimensions, ranked_lists):
        for rank, item in enumerate(ranked, start=1):
            key = item.get("text", "")[:100]  # 텍스트 앞 100자를 키로 사용
            scores[key] += 1.0 / (_RRF_K + rank)
            items[key] = item
            if dim not in matched[key]:
                matched[key].append(dim)

    # 스코어 기준 내림차순 정렬
    sorted_keys = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)

    results = []
    for key in sorted_keys:
        item = items[key].copy()
        item["rrf_score"] = round(scores[key], 6)
        item["matched_questions"] = matched[key]
        results.append(item)

    return results


# ---------------------------------------------------------------------------
# 중복 제거 (텍스트 유사도 기반)
# ---------------------------------------------------------------------------

def _jaccard_similarity(text_a: str, text_b: str) -> float:
    """두 텍스트의 Jaccard 유사도 계산 (단어 단위)."""
    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())
    if not words_a and not words_b:
        return 1.0
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def deduplicate(results: list[dict], threshold: float = 0.8) -> list[dict]:
    """텍스트 유사도 > threshold인 중복 결과 제거. 먼저 등장한 (높은 RRF) 항목 유지."""
    deduplicated = []
    for item in results:
        text = item.get("text", "")
        is_dup = False
        for existing in deduplicated:
            if _jaccard_similarity(text, existing.get("text", "")) > threshold:
                is_dup = True
                break
        if not is_dup:
            deduplicated.append(item)
    return deduplicated


# ---------------------------------------------------------------------------
# 2차 확장 검색 (deep 모드 전용)
# ---------------------------------------------------------------------------

def expand_queries(
    initial_results: list[dict],
    original_query: str,
    max_expansion: int = 2,
) -> list[dict[str, Any]]:
    """
    초기 결과에서 새로운 키워드를 추출하여 2차 확장 검색 쿼리 생성.
    deep 모드에서만 사용.
    """
    # 초기 결과 텍스트에서 빈출 키워드 추출
    all_keywords: dict[str, int] = defaultdict(int)
    original_kw = set(extract_keywords(original_query))

    for item in initial_results:
        for kw in extract_keywords(item.get("text", "")):
            if kw not in original_kw:
                all_keywords[kw] += 1

    # 빈출 순 정렬, 상위 N개로 확장 쿼리 생성
    top_keywords = sorted(all_keywords.keys(), key=lambda k: all_keywords[k], reverse=True)

    expansion_queries = []
    for i in range(min(max_expansion, len(top_keywords))):
        kw = top_keywords[i]
        expansion_queries.append({
            "dimension": "EXPAND",
            "query": f"{original_query} {kw}",
            "keywords": list(original_kw) + [kw],
        })

    return expansion_queries


# ---------------------------------------------------------------------------
# InsightForge 메인 엔진
# ---------------------------------------------------------------------------

def insight_forge(
    query: str,
    depth: str = "light",
) -> dict[str, Any]:
    """
    InsightForge 메인 함수.

    Args:
        query: 사용자 입력 쿼리
        depth: "light" (3개 질문, 5개 결과) 또는 "deep" (5개 질문 + 확장, 15개 결과)

    Returns:
        통합된 검색 결과 딕셔너리
    """
    # 1. 하위 질문 분해
    max_q = 3 if depth == "light" else 5
    max_results = 5 if depth == "light" else 15

    sub_questions = decompose_query(query, max_questions=max_q)

    # 2. 검색 쿼리 생성
    search_queries = build_search_queries(sub_questions)

    # 3. 각 쿼리로 MemPalace 검색
    # ── 실제 사용 시: 이 루프에서 mcp__mempalace__mempalace_search 를 호출 ──
    ranked_lists = []
    dimensions = []
    for sq in search_queries:
        results = search_mempalace(
            query=sq["query"],
            limit=max_results,
        )
        ranked_lists.append(results)
        dimensions.append(sq["dimension"])

    # 4. RRF 통합
    fused = reciprocal_rank_fusion(ranked_lists, dimensions)

    # 5. deep 모드: 2차 확장 검색
    if depth == "deep" and fused:
        expansion_queries = expand_queries(fused, query, max_expansion=2)
        for eq in expansion_queries:
            # ── 실제 사용 시: mcp__mempalace__mempalace_search 호출 ──
            results = search_mempalace(
                query=eq["query"],
                limit=max_results,
            )
            ranked_lists.append(results)
            dimensions.append(eq["dimension"])

        # 확장 포함 재통합
        fused = reciprocal_rank_fusion(ranked_lists, dimensions)
        search_queries.extend(expansion_queries)

    # 6. 중복 제거
    total_before = len(fused)
    deduplicated = deduplicate(fused, threshold=0.8)
    deduplicated = deduplicated[:max_results]

    # 7. 결과 구성
    questions_covered = set()
    for item in deduplicated:
        for dim in item.get("matched_questions", []):
            questions_covered.add(dim)

    return {
        "original_query": query,
        "depth": depth,
        "sub_questions": [
            f"{sq['dimension']}: {sq['question']}" for sq in sub_questions
        ],
        "search_queries": [sq["query"] for sq in search_queries],
        "results": [
            {
                "text": item.get("text", ""),
                "source": item.get("source", ""),
                "rrf_score": item.get("rrf_score", 0.0),
                "matched_questions": item.get("matched_questions", []),
            }
            for item in deduplicated
        ],
        "summary_stats": {
            "total_results": total_before,
            "deduplicated": len(deduplicated),
            "questions_covered": len(questions_covered),
            "questions_total": len(sub_questions),
        },
    }


# ---------------------------------------------------------------------------
# 텍스트 출력 포맷
# ---------------------------------------------------------------------------

def format_text(result: dict[str, Any]) -> str:
    """결과를 사람이 읽기 좋은 텍스트로 포맷."""
    lines = []
    lines.append(f"=== InsightForge 검색 결과 ===")
    lines.append(f"쿼리: {result['original_query']}")
    lines.append(f"깊이: {result['depth']}")
    lines.append("")

    lines.append("── 하위 질문 ──")
    for sq in result["sub_questions"]:
        lines.append(f"  • {sq}")
    lines.append("")

    lines.append("── 검색 쿼리 ──")
    for sq in result["search_queries"]:
        lines.append(f"  → {sq}")
    lines.append("")

    stats = result["summary_stats"]
    lines.append(
        f"── 결과: {stats['deduplicated']}건 "
        f"(전체 {stats['total_results']}건 중 중복 제거) | "
        f"커버 질문: {stats['questions_covered']}/{stats['questions_total']} ──"
    )
    lines.append("")

    if not result["results"]:
        lines.append("  (검색 결과 없음 — MemPalace stub 모드)")
    else:
        for i, item in enumerate(result["results"], 1):
            lines.append(f"  [{i}] (RRF: {item['rrf_score']:.4f}) [{', '.join(item['matched_questions'])}]")
            lines.append(f"      {item['text'][:200]}")
            if item["source"]:
                lines.append(f"      출처: {item['source']}")
            lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="MuchaNipo InsightForge — 다차원 검색 엔진 (MiroFish 패턴)",
    )
    parser.add_argument(
        "query",
        type=str,
        help="검색 쿼리",
    )
    parser.add_argument(
        "--depth",
        choices=["deep", "light"],
        default="light",
        help="검색 깊이: light (3개 질문, 5건) 또는 deep (5개 질문 + 확장, 15건)",
    )
    parser.add_argument(
        "--output",
        choices=["json", "text"],
        default="text",
        help="출력 형식: json 또는 text (기본: text)",
    )

    args = parser.parse_args()

    result = insight_forge(query=args.query, depth=args.depth)

    if args.output == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_text(result))


if __name__ == "__main__":
    main()
