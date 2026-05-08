"""General-purpose public web source-channel search for AutoResearch.

This module intentionally stays domain-neutral. It is not a Korea/AgTech preset;
it is a lightweight source-channel adapter that can retrieve government,
statistics, industry, pricing, adoption, regulatory, and distribution evidence
when the planner emits those facet intents.
"""
from __future__ import annotations

import html
import os
import re
from urllib.parse import parse_qs, quote, unquote, urlparse

import httpx


DEFAULT_TIMEOUT = float(os.getenv("MUCHANIPO_PUBLIC_WEB_TIMEOUT_SECONDS", "10.0"))
DUCKDUCKGO_HTML_URL = "https://html.duckduckgo.com/html/"


def current_timeout() -> float:
    raw = os.getenv("MUCHANIPO_PUBLIC_WEB_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return DEFAULT_TIMEOUT
    try:
        return max(0.1, float(raw))
    except ValueError:
        return DEFAULT_TIMEOUT


def search(query: str, *, limit: int = 5) -> list[dict[str, object]]:
    """Return normalized public-web search hits for a source-channel query.

    The adapter uses DuckDuckGo's HTML endpoint because it needs no project
    secrets and degrades gracefully to an empty list. Callers still apply
    Muchanipo's source-side topic relevance and facet gates before accepting any
    result.
    """

    query = " ".join(str(query or "").split())
    if not query:
        return []
    try:
        response = httpx.get(
            DUCKDUCKGO_HTML_URL,
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0 Muchanipo public source research"},
            timeout=current_timeout(),
        )
        response.raise_for_status()
    except Exception:  # noqa: BLE001 - search is best-effort and must not abort pipeline
        return _search_korean_public_data(query, limit=max(1, limit))
    hits = _parse_duckduckgo_html(response.text, limit=max(1, limit))
    if hits:
        return hits
    return _search_korean_public_data(query, limit=max(1, limit))


def _search_korean_public_data(query: str, *, limit: int = 5) -> list[dict[str, object]]:
    """Fallback source-channel search for Korean public/government data pages.

    Verification-19 showed that the public web source-channel can degrade when
    DuckDuckGo's HTML endpoint times out. For Korean government/statistics
    source-channel queries, query data.go.kr directly and parse result metadata
    from the HTML page. This stays general-purpose: it is only a public-data
    channel fallback for Korean/statistics/market intents, not a vertical
    preset.
    """

    if not _looks_like_korean_public_data_query(query):
        return []
    url = f"https://www.data.go.kr/tcs/dss/selectDataSetList.do?keyword={quote(query)}"
    try:
        response = httpx.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 Muchanipo public source research"},
            timeout=current_timeout(),
        )
        response.raise_for_status()
    except Exception:  # noqa: BLE001 - best-effort fallback
        return []
    return _parse_data_go_kr_html(response.text, query=query, source_url=url, limit=max(1, limit))


def _looks_like_korean_public_data_query(query: str) -> bool:
    text = str(query or "").casefold()
    has_korean = bool(re.search(r"[가-힣]", text))
    has_public_channel = any(
        marker in text
        for marker in (
            "통계",
            "공식",
            "공공데이터",
            "농촌진흥청",
            "통계청",
            "kosis",
            "정부",
            "가격",
            "구매",
            "소비",
            "유통",
            "도입",
            "시장",
            "market",
            "pricing",
            "adoption",
        )
    )
    return has_korean and has_public_channel


def _parse_data_go_kr_html(
    markup: str,
    *,
    query: str,
    source_url: str,
    limit: int = 5,
) -> list[dict[str, object]]:
    query_terms = _korean_public_terms(query)
    hits: list[dict[str, object]] = []
    seen: set[str] = set()
    for match in re.finditer(r'value="(?P<title>[^"]{2,160})"', markup or "", flags=re.IGNORECASE):
        title = _clean_html(match.group("title"))
        if not title or title in seen or not _data_go_title_is_candidate(title, query=query):
            continue
        window = markup[max(0, match.start() - 900) : match.end() + 1800]
        snippet = _clean_html(window)
        relevance_snippet = f"{query} {snippet}"
        if not _data_go_result_is_relevant(title=title, snippet=relevance_snippet, query_terms=query_terms):
            continue
        seen.add(title)
        kind = _source_kind_for(url=source_url, title=title, snippet=snippet)
        score = _data_go_score(title=title, snippet=snippet, query_terms=query_terms)
        hits.append(
            {
                "kind": kind if kind != "web" else "government",
                "url": source_url,
                "source": source_url,
                "title": title,
                "text": " ".join(part for part in (title, f"검색어: {query}", snippet[:420]) if part).strip(),
                "score": score,
            }
        )
    hits.sort(key=lambda hit: float(hit.get("score") or 0.0), reverse=True)
    return hits[: max(1, limit)]


def _korean_public_terms(query: str) -> set[str]:
    terms = {term.casefold() for term in re.findall(r"[A-Za-z0-9]+|[가-힣]{2,}", str(query or ""))}
    stop = {
        "공식",
        "통계",
        "가격",
        "구매",
        "소비",
        "트렌드",
        "도입",
        "유통",
        "규제",
        "시장",
        "시장성",
        "source",
        "backed",
        "deep",
        "research",
        "council",
        "persona",
    }
    return {term for term in terms if term not in stop and not re.fullmatch(r"\d+[a-z]?", term)}


def _data_go_title_is_candidate(title: str, *, query: str) -> bool:
    normalized = " ".join(str(title or "").split())
    lowered = normalized.casefold()
    if not normalized or normalized == "0" or normalized == "10":
        return False
    if normalized == " ".join(str(query or "").split()):
        return False
    if lowered in {"search", "pbde07", "공공행정", "과학기술", "교육", "교통물류", "국토관리", "문화관광"}:
        return False
    if not re.search(r"[가-힣]", normalized):
        return False
    # General Korean market/pricing/statistics markers (domain-agnostic)
    return any(
        marker in normalized
        for marker in (
            "가격",
            "경락",
            "경매",
            "소비",
            "행태",
            "유통",
            "시장",
            "통계",
            "도입",
            "규제",
        )
    )


def _data_go_result_is_relevant(*, title: str, snippet: str, query_terms: set[str]) -> bool:
    text = f"{title} {snippet}".casefold()
    if query_terms and not any(term in text for term in query_terms):
        return False
    return any(
        marker in text
        for marker in (
            "가격",
            "경락",
            "경매",
            "도매",
            "소비",
            "구매",
            "행태",
            "유통",
            "시장",
            "통계",
            "도입",
            "규제",
        )
    )


def _data_go_score(*, title: str, snippet: str, query_terms: set[str]) -> float:
    text = f"{title} {snippet}".casefold()
    overlap = sum(1 for term in query_terms if term in text)
    channel_bonus = 0.08 if any(marker in text for marker in ("가격", "경락", "경매", "소비", "구매", "유통", "통계")) else 0.0
    return round(min(0.95, 0.78 + min(0.09, overlap * 0.03) + channel_bonus), 3)


def _parse_duckduckgo_html(markup: str, *, limit: int = 5) -> list[dict[str, object]]:
    hits: list[dict[str, object]] = []
    for match in re.finditer(
        r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
        markup,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        url = _clean_duckduckgo_url(html.unescape(match.group("href")))
        title = _clean_html(match.group("title"))
        if not url or not title:
            continue
        snippet = _snippet_after(markup, match.end())
        kind = _source_kind_for(url=url, title=title, snippet=snippet)
        hits.append(
            {
                "kind": kind,
                "url": url,
                "source": url,
                "title": title,
                "text": " ".join(part for part in (title, snippet) if part).strip(),
                "score": 0.82 if kind in {"government", "statistics", "industry_report"} else 0.72,
            }
        )
        if len(hits) >= limit:
            break
    return hits


def _snippet_after(markup: str, offset: int) -> str:
    window = markup[offset : offset + 1600]
    match = re.search(
        r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(?P<snippet>.*?)</a>|<div[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(?P<divsnippet>.*?)</div>',
        window,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return ""
    return _clean_html(match.group("snippet") or match.group("divsnippet") or "")


def _clean_html(value: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", value or "")
    return " ".join(html.unescape(no_tags).split())


def _clean_duckduckgo_url(value: str) -> str:
    url = html.unescape(value or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        url = f"https:{url}"
    parsed = urlparse(url)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        uddg = parse_qs(parsed.query).get("uddg", [""])[0]
        if uddg:
            return unquote(uddg)
    return url


def _source_kind_for(*, url: str, title: str, snippet: str) -> str:
    haystack = f"{url} {title} {snippet}".casefold()
    if any(marker in haystack for marker in (".go.kr", "go.kr/", ".gov", "government", "ministry", "kosis", "통계청", "농촌진흥청", "농림축산식품부")):
        return "government"
    if any(marker in haystack for marker in ("statistics", "statistical", "kosis", "statista", "통계", "survey", "조사")):
        return "statistics"
    if any(marker in haystack for marker in ("industry report", "market report", "시장 보고서", "산업 보고서")):
        return "industry_report"
    if any(marker in haystack for marker in ("price", "pricing", "가격", "shop", "store")):
        return "pricing_page"
    return "web"
