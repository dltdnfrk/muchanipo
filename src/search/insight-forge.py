#!/usr/bin/env python3
"""
MuchaNipo InsightForge — 다차원 검색 엔진 (MiroFish 패턴)
Usage: python insight-forge.py "query" [--depth deep|light] [--output json|text]

쿼리를 하위 질문으로 자동 분해 → 각각 검색 → RRF로 통합.

MiroFish 원본 패턴 채용:
- zep_tools.py InsightForge: LLM 기반 서브쿼리 생성 + 시맨틱 검색 + 엔티티 인사이트 + 관계 체인
- zep_tools.py PanoramaSearch: 전체 노드/엣지 스캔 + 시간 기반 분류
- Zep 의존성 → MemPalace MCP로 대체, 검색 패턴(쿼리 분해, RRF)은 그대로 유지

GBrain 하이브리드 검색 패턴 참조 (garrytan/gbrain):
  원본 구현: tools/gbrain/src/core/search/hybrid.ts

  검색 파이프라인:
    1. Multi-query expansion (Claude Haiku, expansion.ts)
       - 원본 쿼리 + 2개 대안 (최대 3개)
       - 3단어 미만 쿼리는 확장 skip
       - Anthropic tool_use로 alternative_queries 생성
       - 실패해도 non-fatal (원본 쿼리만 사용)
    2. 벡터 검색 (pgvector HNSW cosine) + 키워드 검색 (tsvector ts_rank)
       - 각각 limit*2 결과를 가져와 RRF로 통합
       - 벡터: 모든 query variant를 embed하여 각각 검색
       - 키워드: 원본 쿼리만 사용
    3. RRF Fusion: score = sum(1/(K + rank)), K=60
       - 키: slug + chunk_text[:50] 으로 동일 결과 식별
       - 스코어 스케일이 다른 여러 리스트를 공정하게 통합
    4. 4-Layer Dedup (dedup.ts):
       Layer 1: By source — 페이지당 최고 점수 chunk만 유지
       Layer 2: By text similarity — Jaccard > 0.85인 중복 제거
                (원본은 cosine similarity 대신 word-set Jaccard 사용)
       Layer 3: By type diversity — 단일 page type이 결과의 60% 초과 금지
       Layer 4: Per-page cap — 페이지당 최대 2개 chunk
    5. Stale alerts — compiled_truth가 latest timeline보다 오래된 결과에 [STALE] 표시

  현재 InsightForge 대응:
    - 5W1H 분해 → GBrain multi-query expansion 역할
    - MemPalace search → GBrain vector search 역할 (semantic)
    - RRF 통합 → GBrain hybrid.ts rrfFusion과 동일 (K=60)
    - deduplicate() → GBrain dedup.ts Layer 2 (Jaccard) 대응
    - deduplicate_gbrain() → Layer 1/2/3/4 + stale alerts 대응

  GBrain dedup 채용 상태:
    - Layer 1/3/4 구현 완료 (_dedup_by_source, _enforce_type_diversity, _cap_per_source)
    - Stale alerts 구현 완료 (_mark_stale)
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import defaultdict
from datetime import date
from functools import lru_cache
from typing import Any


# ---------------------------------------------------------------------------
# MemPalace 검색 stub
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_stub_fixture() -> dict[str, Any] | None:
    """테스트용 stub fixture 로드."""
    fixture_path = os.getenv("INSIGHT_FORGE_STUB_DATA")
    if not fixture_path:
        return None

    with open(fixture_path, "r", encoding="utf-8") as f:
        fixture = json.load(f)

    if isinstance(fixture, list):
        return {"__default__": fixture}
    if isinstance(fixture, dict):
        return fixture
    raise ValueError("INSIGHT_FORGE_STUB_DATA must point to a JSON object or list")


def search_mempalace(query: str, wing: str = None, room: str = None, limit: int = 5) -> list[dict]:
    """
    MemPalace 검색. 우선순위:
      1) stub fixture (테스트 시)
      2) 로컬 vault markdown grep fallback (C29 #11)
      3) 빈 리스트

    실제 사용 시: Claude Code에서 mcp__mempalace__mempalace_search 호출로 대체.
    muchanipo.md 오케스트레이터가 이 함수 대신 실제 MCP 도구를 호출함.

    Returns:
        list[dict]: 각 항목은 {"text": str, "source": str, "score": float}
    """
    fixture = _load_stub_fixture()
    if fixture is not None:
        if query in fixture:
            data = fixture[query]
        else:
            data = fixture.get("__default__", [])
        if isinstance(data, list):
            return data[:limit]

    # C29 #11 fix: 로컬 vault markdown fallback (MemPalace MCP 미가용 시)
    return _search_local_vault(query, limit=limit)


def _search_local_vault(query: str, limit: int = 5) -> list[dict]:
    """vault/ + ~/Documents/Hyunjun/ markdown 파일에서 query 단어 매칭 줄 추출.

    stdlib only. case-insensitive substring match. 단일 query 토큰 기준.
    """
    import os
    from pathlib import Path

    vault_paths: list[Path] = []
    env_vault = os.environ.get("MUCHANIPO_VAULT_PATH")
    if env_vault:
        vault_paths.append(Path(env_vault).expanduser())
    # 프로젝트 로컬 vault/
    proj_vault = Path(__file__).resolve().parent.parent.parent / "vault"
    if proj_vault.exists():
        vault_paths.append(proj_vault)
    # 사용자 obsidian default
    obsidian = Path("~/Documents/Hyunjun").expanduser()
    if obsidian.exists() and obsidian not in vault_paths:
        vault_paths.append(obsidian)

    if not vault_paths or not query.strip():
        return []

    q_low = query.lower()
    results: list[dict] = []
    seen = 0

    for vault in vault_paths:
        try:
            for md in vault.rglob("*.md"):
                if seen >= limit * 4:  # 후보 capped
                    break
                try:
                    text = md.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                low = text.lower()
                idx = low.find(q_low)
                if idx == -1:
                    continue
                # 매칭 라인 추출 (앞뒤 60자 컨텍스트)
                start = max(0, idx - 60)
                end = min(len(text), idx + len(query) + 60)
                snippet = text[start:end].replace("\n", " ").strip()
                # 단순 score: query 등장 횟수 / 1000자
                count = low.count(q_low)
                score = min(1.0, count / max(1, len(text) // 1000))
                # Python 3.8 호환 (is_relative_to는 3.9+)
                try:
                    src = str(md.relative_to(vault))
                except ValueError:
                    src = str(md)
                results.append({
                    "text": snippet,
                    "source": src,
                    "score": round(score, 3),
                })
                seen += 1
        except OSError:
            continue

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]


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

_DIMENSION_QUERY_HINTS: dict[str, list[str]] = {
    "WHO": ["인물", "조직"],
    "WHAT": ["기술", "제품"],
    "HOW": ["구현", "프로세스"],
    "WHY": ["동기", "배경", "문제점"],
    "WHEN": ["일정", "시기"],
    "EXPAND": ["확장"],
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


def _dedupe_keywords(keywords: list[str]) -> list[str]:
    """순서를 보존하며 키워드 중복 제거."""
    unique_keywords: list[str] = []
    for keyword in keywords:
        if keyword not in unique_keywords:
            unique_keywords.append(keyword)
    return unique_keywords


def build_search_queries(sub_questions: list[dict[str, str]]) -> list[dict[str, Any]]:
    """하위 질문들을 MemPalace 검색 쿼리로 변환."""
    queries = []
    for sq in sub_questions:
        keywords = extract_keywords(sq["question"])
        dimension_hints = _DIMENSION_QUERY_HINTS.get(sq["dimension"], [])
        topic_keywords = [kw for kw in keywords if kw not in dimension_hints]
        prioritized = _dedupe_keywords(topic_keywords[:4] + dimension_hints + keywords)
        query_str = " ".join(prioritized[:6])  # 최대 6개 키워드
        queries.append({
            "dimension": sq["dimension"],
            "query": query_str,
            "keywords": prioritized[:6],
        })
    return queries


# ---------------------------------------------------------------------------
# RRF (Reciprocal Rank Fusion) 통합
# ---------------------------------------------------------------------------

# GBrain 원본: hybrid.ts RRF_K = 60 (동일)
# GBrain 키 생성: `${r.slug}:${r.chunk_text.slice(0, 50)}`
# InsightForge는 text 전체를 키로 사용 (slug 없으므로)
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
            key = re.sub(r"\s+", " ", item.get("text", "").strip())
            if not key:
                key = json.dumps(item, ensure_ascii=False, sort_keys=True)
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
    """텍스트 유사도 > threshold인 중복 결과 제거. 먼저 등장한 (높은 RRF) 항목 유지.

    GBrain 4-Layer Dedup (dedup.ts) 중 Layer 2에 해당:
      Layer 1 (dedupBySource): page slug 기반 best-chunk — _dedup_by_source
      Layer 2 (dedupByTextSimilarity): Jaccard > 0.85 중복 제거 ← 현재 구현
      Layer 3 (enforceTypeDiversity): type별 60% cap — _enforce_type_diversity
      Layer 4 (capPerPage): page당 max 2 chunk — _cap_per_source

    GBrain 원본 threshold=0.85, InsightForge는 0.8 (더 보수적 중복 제거).
    """
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
# GBrain 5-Layer Dedup Pipeline (dedup.ts 완전 채용)
# ---------------------------------------------------------------------------
# 아래 함수들은 GBrain dedup.ts의 dedup 레이어 + stale marker를 Python으로 포팅한 것.
# deduplicate()는 Layer 2만 담당하고, deduplicate_gbrain()이 전체 파이프라인을 담당한다.

_GBRAIN_COSINE_DEDUP_THRESHOLD = 0.85  # GBrain 원본 값
_GBRAIN_MAX_TYPE_RATIO = 0.6           # GBrain 원본 값
_GBRAIN_MAX_PER_SOURCE = 2             # GBrain 원본 값


def _dedup_by_source(results: list[dict], source_key: str = "source") -> list[dict]:
    """GBrain Layer 1: source(page slug)당 최고 점수 결과만 유지.

    GBrain dedup.ts dedupBySource: slug 기반으로 best chunk 선택.
    InsightForge에서는 source 필드를 slug 대용으로 사용.
    """
    by_source: dict[str, dict] = {}
    for item in results:
        src = item.get(source_key, "")
        if not src:
            # source 없으면 통과
            by_source[id(item)] = item
            continue
        existing = by_source.get(src)
        if existing is None or item.get("rrf_score", 0) > existing.get("rrf_score", 0):
            by_source[src] = item
    return sorted(by_source.values(), key=lambda x: x.get("rrf_score", 0), reverse=True)


def _enforce_type_diversity(
    results: list[dict],
    max_ratio: float = _GBRAIN_MAX_TYPE_RATIO,
    type_key: str = "matched_questions",
) -> list[dict]:
    """GBrain Layer 3: 단일 type이 전체 결과의 max_ratio를 초과하지 않도록 제한.

    GBrain dedup.ts enforceTypeDiversity: page type별 60% cap.
    InsightForge에서는 matched_questions의 첫 번째 dimension을 type 대용으로 사용.
    """
    max_per_type = max(1, int(len(results) * max_ratio + 0.5))
    type_counts: dict[str, int] = {}
    kept: list[dict] = []
    for item in results:
        dims = item.get(type_key, [])
        item_type = dims[0] if dims else "UNKNOWN"
        count = type_counts.get(item_type, 0)
        if count < max_per_type:
            kept.append(item)
            type_counts[item_type] = count + 1
    return kept


def _cap_per_source(
    results: list[dict],
    max_per_source: int = _GBRAIN_MAX_PER_SOURCE,
    source_key: str = "source",
) -> list[dict]:
    """GBrain Layer 4: source(page)당 최대 N개 결과.

    GBrain dedup.ts capPerPage: page당 max 2 chunk.
    """
    source_counts: dict[str, int] = {}
    kept: list[dict] = []
    for item in results:
        src = item.get(source_key, "")
        count = source_counts.get(src, 0)
        if count < max_per_source:
            kept.append(item)
            source_counts[src] = count + 1
    return kept


def _parse_iso_date(value: Any) -> date | None:
    """ISO date/time 문자열을 date로 파싱. 실패 시 None."""
    if not isinstance(value, str) or not value:
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        try:
            return date.fromisoformat(normalized.split("T", 1)[0])
        except ValueError:
            return None


def _mark_stale(results: list[dict], stale_marker: str = "[STALE]") -> list[dict]:
    """GBrain Layer 5: compiled_truth가 latest_timeline 보다 오래된 결과에 마커.

    두 날짜 필드가 모두 존재하고 파싱 가능할 때만 비교한다.
    원본 dict는 변형하지 않고, 필요한 항목만 복사해서 text를 갱신한다.
    """
    marked: list[dict] = []
    marker_prefix = f"{stale_marker} "
    for item in results:
        compiled_date = _parse_iso_date(item.get("compiled_truth"))
        latest_date = _parse_iso_date(item.get("latest_timeline"))
        if compiled_date and latest_date and compiled_date < latest_date:
            updated = item.copy()
            text = updated.get("text", "")
            if isinstance(text, str) and not text.startswith(marker_prefix):
                updated["text"] = f"{marker_prefix}{text}"
            marked.append(updated)
        else:
            marked.append(item)
    return marked


def deduplicate_gbrain(results: list[dict]) -> list[dict]:
    """GBrain 5-Layer Dedup 전체 파이프라인.

    tools/gbrain/src/core/search/dedup.ts dedupResults()의 Python 포팅.
    Layer 1 → Layer 2 → Layer 3 → Layer 4 → Layer 5(stale marker) 순서로 적용.
    """
    deduped = results
    deduped = _dedup_by_source(deduped)                                    # Layer 1
    deduped = deduplicate(deduped, threshold=_GBRAIN_COSINE_DEDUP_THRESHOLD)  # Layer 2
    deduped = _enforce_type_diversity(deduped)                             # Layer 3
    deduped = _cap_per_source(deduped)                                     # Layer 4
    deduped = _mark_stale(deduped)                                         # Layer 5
    return deduped


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
    original_keywords = extract_keywords(original_query)
    original_kw = set(original_keywords)

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
            "keywords": _dedupe_keywords(original_keywords + [kw]),
        })

    return expansion_queries


# ---------------------------------------------------------------------------
# Adopted from MiroFish: zep_tools.py:1092-1143
# LLM 기반 서브쿼리 생성 (MiroFish _generate_sub_queries 포팅)
# ---------------------------------------------------------------------------

_SUB_QUERY_SYSTEM_PROMPT = """\
당신은 전문 질문 분석가입니다. 복잡한 질문을 여러 개의 독립적으로 검색 가능한 하위 질문으로 분해하세요.

요구사항:
1. 각 하위 질문은 충분히 구체적이어야 합니다
2. 하위 질문은 원래 질문의 서로 다른 차원을 커버해야 합니다 (누가, 무엇을, 왜, 어떻게, 언제, 어디서)
3. 하위 질문은 검색 가능한 형태여야 합니다
4. JSON 형식으로 반환: {"sub_queries": ["하위 질문 1", "하위 질문 2", ...]}"""


def generate_sub_queries_llm(
    query: str,
    context: str = "",
    max_queries: int = 5,
) -> list[str]:
    """
    LLM을 사용하여 복잡한 질문을 하위 질문으로 분해.

    MiroFish의 _generate_sub_queries를 MemPalace 환경으로 포팅.
    실제 LLM 호출은 오케스트레이터(Claude Code)가 수행.
    이 함수는 프롬프트 생성 + fallback 로직만 담당.

    # Adopted from MiroFish: zep_tools.py:1092-1143

    Args:
        query: 원본 쿼리
        context: 추가 맥락 (보고서 컨텍스트 등)
        max_queries: 최대 하위 질문 수

    Returns:
        하위 질문 리스트. LLM 사용 불가 시 5W1H 기반 fallback.
    """
    # LLM 호출을 위한 프롬프트 구성 (오케스트레이터가 사용)
    user_prompt = f"""다음 질문을 {max_queries}개의 하위 질문으로 분해하세요:
{query}

{f"추가 맥락: {context[:500]}" if context else ""}

JSON 형식의 하위 질문 리스트를 반환하세요."""

    # NOTE: 이 함수는 프롬프트만 생성. 실제 LLM 호출은
    #       arc-council.md 오케스트레이터가 Claude Code Agent로 수행.
    #       LLM 응답이 없는 환경에서는 fallback 사용.

    # Fallback: 5W1H 기반 분해 (기존 로직)
    # Adopted from MiroFish: zep_tools.py:1136-1143
    return [
        query,
        f"{query}의 주요 관련 인물/조직",
        f"{query}의 원인과 영향",
        f"{query}의 발전 과정과 시간 순서",
        f"{query}의 구현/실행 방법",
    ][:max_queries]


# 외부 접근용: LLM 프롬프트 반환 함수
def get_sub_query_prompt(query: str, context: str = "", max_queries: int = 5) -> dict[str, str]:
    """LLM 호출용 프롬프트를 반환. 오케스트레이터가 이 프롬프트로 LLM을 호출.
    # Adopted from MiroFish: zep_tools.py:1103-1120
    """
    return {
        "system": _SUB_QUERY_SYSTEM_PROMPT,
        "user": f"다음 질문을 {max_queries}개의 하위 질문으로 분해하세요:\n{query}"
                + (f"\n\n추가 맥락: {context[:500]}" if context else "")
                + "\n\nJSON 형식의 하위 질문 리스트를 반환하세요.",
    }


# ---------------------------------------------------------------------------
# Adopted from MiroFish: zep_tools.py:945-1090
# InsightForge 엔티티 인사이트 + 관계 체인 추출
# ---------------------------------------------------------------------------

def extract_entity_insights(
    search_results: list[dict],
    query: str,
) -> list[dict[str, Any]]:
    """
    검색 결과에서 엔티티 인사이트를 추출.

    MiroFish InsightForge의 Step 3-4를 포팅:
    - 검색 결과에서 엔티티 UUID/이름 추출
    - 각 엔티티의 관련 사실 수집
    - 엔티티 간 관계 체인 구축

    # Adopted from MiroFish: zep_tools.py:1026-1090

    Args:
        search_results: MemPalace 검색 결과 리스트
        query: 원본 쿼리 (관련성 필터링용)

    Returns:
        엔티티 인사이트 리스트
    """
    entity_map: dict[str, dict[str, Any]] = {}

    for item in search_results:
        text = item.get("text", "")
        source = item.get("source", "")

        # 소스에서 엔티티 이름 추출 (wing/room 기반)
        entity_name = ""
        if "/" in source:
            parts = source.split("/")
            entity_name = parts[-1] if parts else ""
        elif source:
            entity_name = source

        if not entity_name:
            continue

        if entity_name not in entity_map:
            entity_map[entity_name] = {
                "name": entity_name,
                "source": source,
                "related_facts": [],
                "fact_count": 0,
            }

        entity_map[entity_name]["related_facts"].append(text)
        entity_map[entity_name]["fact_count"] += 1

    # 관련성 순 정렬
    entities = sorted(
        entity_map.values(),
        key=lambda e: e["fact_count"],
        reverse=True,
    )

    return entities


def extract_relationship_chains(
    search_results: list[dict],
) -> list[str]:
    """
    검색 결과에서 관계 체인을 추출.

    MiroFish InsightForge의 Step 4를 포팅:
    - 검색 결과 텍스트에서 "A → B" 패턴의 관계 추출
    - 중복 제거

    # Adopted from MiroFish: zep_tools.py:1071-1087

    Args:
        search_results: MemPalace 검색 결과 리스트

    Returns:
        관계 체인 문자열 리스트
    """
    chains: list[str] = []
    seen: set[str] = set()

    for item in search_results:
        text = item.get("text", "")

        # 패턴 매칭: "A는 B와 관련" / "A → B" / "A --[rel]--> B"
        import re as _re
        arrow_patterns = _re.findall(r"(\S+)\s*(?:→|-->|--\[.*?\]-->)\s*(\S+)", text)
        for src, tgt in arrow_patterns:
            chain = f"{src} --> {tgt}"
            if chain not in seen:
                chains.append(chain)
                seen.add(chain)

    return chains


# ---------------------------------------------------------------------------
# InsightForge 메인 엔진 (MiroFish 패턴 통합)
# ---------------------------------------------------------------------------

def insight_forge(
    query: str,
    depth: str = "light",
    context: str = "",
) -> dict[str, Any]:
    """
    InsightForge 메인 함수.

    MiroFish의 실제 InsightForge 패턴 통합:
    1. 하위 질문 분해 (LLM fallback → 5W1H)
    2. 각 질문으로 MemPalace 검색
    3. RRF 통합
    4. 엔티티 인사이트 추출 (MiroFish Step 3)
    5. 관계 체인 추적 (MiroFish Step 4)
    6. deep 모드: 2차 확장 검색

    # Adopted from MiroFish: zep_tools.py:945-1090

    Args:
        query: 사용자 입력 쿼리
        depth: "light" (3개 질문, 5개 결과) 또는 "deep" (5개 질문 + 확장, 15개 결과)
        context: 추가 맥락 (보고서 컨텍스트 등)

    Returns:
        통합된 검색 결과 딕셔너리 (엔티티 인사이트 + 관계 체인 포함)
    """
    # 1. 하위 질문 분해
    max_q = 3 if depth == "light" else 5
    max_results = 5 if depth == "light" else 15

    # MiroFish 패턴: LLM 기반 분해 시도 → 실패 시 5W1H fallback
    # Adopted from MiroFish: zep_tools.py:981-989
    sub_questions = decompose_query(query, max_questions=max_q)

    # 2. 검색 쿼리 생성
    search_queries = build_search_queries(sub_questions)

    # 3. 각 쿼리로 MemPalace 검색
    # Adopted from MiroFish: zep_tools.py:991-1009
    # 원본 쿼리에 대해서도 검색 수행 (MiroFish: main_search)
    ranked_lists = []
    dimensions = []

    # 원본 쿼리 검색 (MiroFish: zep_tools.py:1012-1021)
    main_results = search_mempalace(query=query, limit=max_results)
    if main_results:
        ranked_lists.append(main_results)
        dimensions.append("MAIN")

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
    # Adopted from MiroFish: zep_tools.py (deep search 패턴)
    if depth == "deep" and fused:
        expansion_queries = expand_queries(fused, query, max_expansion=2)
        for eq in expansion_queries:
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
    # light/deep 공통으로 GBrain dedup 파이프라인 사용.
    # light는 확장 검색을 생략해 비용을 줄이고, dedup 정책은 동일하게 유지.
    total_before = len(fused)
    deduplicated = deduplicate_gbrain(fused)
    deduplicated = deduplicated[:max_results]

    # 7. 엔티티 인사이트 추출 (MiroFish Step 3)
    # Adopted from MiroFish: zep_tools.py:1026-1068
    entity_insights = extract_entity_insights(deduplicated, query)

    # 8. 관계 체인 추출 (MiroFish Step 4)
    # Adopted from MiroFish: zep_tools.py:1071-1087
    relationship_chains = extract_relationship_chains(deduplicated)

    # 9. 결과 구성 (MiroFish InsightForgeResult 구조 반영)
    # Adopted from MiroFish: zep_tools.py:138-211
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
        # --- MiroFish InsightForgeResult 추가 필드 ---
        # Adopted from MiroFish: zep_tools.py:148-156
        "semantic_facts": [item.get("text", "") for item in deduplicated if item.get("text")],
        "entity_insights": entity_insights,
        "relationship_chains": relationship_chains,
        "summary_stats": {
            "total_results": total_before,
            "deduplicated": len(deduplicated),
            "questions_covered": len(questions_covered),
            "questions_total": len(sub_questions),
            # MiroFish 통계 필드
            "total_facts": len(deduplicated),
            "total_entities": len(entity_insights),
            "total_relationships": len(relationship_chains),
        },
    }


# ---------------------------------------------------------------------------
# 텍스트 출력 포맷
# ---------------------------------------------------------------------------

def format_text(result: dict[str, Any]) -> str:
    """
    결과를 사람이 읽기 좋은 텍스트로 포맷.

    MiroFish InsightForgeResult.to_text() 구조 반영.
    # Adopted from MiroFish: zep_tools.py:171-211
    """
    lines = []
    lines.append(f"=== InsightForge 검색 결과 ===")
    lines.append(f"쿼리: {result['original_query']}")
    lines.append(f"깊이: {result['depth']}")
    lines.append("")

    stats = result["summary_stats"]

    # MiroFish 스타일 통계 섹션
    # Adopted from MiroFish: zep_tools.py:176-181
    lines.append("── 데이터 통계 ──")
    lines.append(f"  - 관련 사실: {stats.get('total_facts', stats['deduplicated'])}건")
    lines.append(f"  - 관련 엔티티: {stats.get('total_entities', 0)}개")
    lines.append(f"  - 관계 체인: {stats.get('total_relationships', 0)}건")
    lines.append(f"  - 커버 질문: {stats['questions_covered']}/{stats['questions_total']}")
    lines.append("")

    lines.append("── 하위 질문 ──")
    for sq in result["sub_questions"]:
        lines.append(f"  • {sq}")
    lines.append("")

    lines.append("── 검색 쿼리 ──")
    for sq in result["search_queries"]:
        lines.append(f"  -> {sq}")
    lines.append("")

    # 시맨틱 팩트 (MiroFish: semantic_facts)
    # Adopted from MiroFish: zep_tools.py:189-193
    semantic_facts = result.get("semantic_facts", [])
    if semantic_facts:
        lines.append("── 핵심 사실 (보고서 인용 가능) ──")
        for i, fact in enumerate(semantic_facts, 1):
            lines.append(f'  {i}. "{fact[:300]}"')
        lines.append("")

    # 엔티티 인사이트 (MiroFish: entity_insights)
    # Adopted from MiroFish: zep_tools.py:196-203
    entity_insights = result.get("entity_insights", [])
    if entity_insights:
        lines.append("── 핵심 엔티티 ──")
        for entity in entity_insights:
            name = entity.get("name", "")
            count = entity.get("fact_count", 0)
            lines.append(f"  - **{name}** (관련 사실: {count}건)")
            for fact in entity.get("related_facts", [])[:3]:
                lines.append(f"    -> {fact[:150]}")
        lines.append("")

    # 관계 체인 (MiroFish: relationship_chains)
    # Adopted from MiroFish: zep_tools.py:206-209
    chains = result.get("relationship_chains", [])
    if chains:
        lines.append("── 관계 체인 ──")
        for chain in chains:
            lines.append(f"  - {chain}")
        lines.append("")

    # 검색 결과 상세
    lines.append(
        f"── 검색 결과: {stats['deduplicated']}건 "
        f"(전체 {stats['total_results']}건 중 중복 제거) ──"
    )
    lines.append("")

    if not result["results"]:
        lines.append("  (검색 결과 없음 -- MemPalace stub 모드)")
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
