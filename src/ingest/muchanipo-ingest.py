#!/usr/bin/env python3
"""
MuchaNipo Document Ingest Pipeline
===================================
MiroFish 패턴 기반 문서 인제스트: PDF/텍스트 → 청킹 → MemPalace 저장

Usage:
    python muchanipo-ingest.py <file_path> [--chunk-size 500] [--overlap 50] [--wing neobio]
    python muchanipo-ingest.py <file_path> --extract-ontology [--dry-run]

Requires: .omc/autoresearch/mp-env/ venv with mempalace installed
"""

import argparse
import importlib.util
import json
import os
import re
import sys
import subprocess
from collections import Counter
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional


SCRIPT_DIR = Path(__file__).resolve().parent


def _load_runtime_paths():
    spec = importlib.util.spec_from_file_location(
        "muchanipo_runtime_paths",
        SCRIPT_DIR.parent / "runtime" / "paths.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_runtime_paths = _load_runtime_paths()


# ============================================================
# 1. TEXT EXTRACTION (No model needed - pure code)
# ============================================================

_PDFTOTEXT_TIMEOUT = int(os.environ.get("PDFTOTEXT_TIMEOUT", "60"))


def extract_text_from_pdf(file_path: str) -> str:
    """PDF에서 텍스트 추출 (pdftotext 또는 Python fallback)"""
    # Try pdftotext first (faster, better quality)
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", file_path, "-"],
            capture_output=True, text=True, timeout=_PDFTOTEXT_TIMEOUT
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback: try PyPDF2 or pdfplumber
    try:
        import pdfplumber
        text_parts = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text)
        return "\n\n".join(text_parts)
    except ImportError:
        pass

    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(file_path)
        text_parts = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)
        return "\n\n".join(text_parts)
    except ImportError:
        pass

    print("WARNING: No PDF parser available. Install pdfplumber or PyPDF2.")
    print("  pip install pdfplumber")
    return ""


def extract_text(file_path: str) -> str:
    """파일에서 텍스트 추출 (PDF, TXT, MD, HTML 지원)"""
    path = Path(file_path)
    ext = path.suffix.lower()

    if ext == ".pdf":
        return extract_text_from_pdf(file_path)
    elif ext in (".txt", ".md", ".markdown"):
        return path.read_text(encoding="utf-8")
    elif ext in (".html", ".htm"):
        text = path.read_text(encoding="utf-8")
        # Simple HTML tag stripping
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()
    elif ext == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        return json.dumps(data, ensure_ascii=False, indent=2)
    else:
        # Try reading as text
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            print(f"ERROR: Cannot read {file_path} as text")
            return ""


# ============================================================
# 2. TEXT PREPROCESSING & CHUNKING (No model needed)
# ============================================================

def preprocess_text(text: str) -> str:
    """텍스트 전처리 (MiroFish TextProcessor 패턴)"""
    # Normalize newlines
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    # Remove excessive blank lines (keep max 2)
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Strip leading/trailing whitespace per line
    lines = [line.strip() for line in text.split('\n')]
    text = '\n'.join(lines)
    return text.strip()


def split_text_into_chunks(
    text: str,
    chunk_size: int = 500,
    overlap: int = 50
) -> List[Dict[str, Any]]:
    """
    텍스트를 청크로 분할 (MiroFish 패턴: 500자, 50자 오버랩)

    Returns list of dicts with:
    - text: chunk content
    - index: chunk number (0-based)
    - start: character offset
    - end: character offset
    """
    chunks = []
    start = 0
    index = 0

    while start < len(text):
        end = start + chunk_size

        # Try to break at sentence/paragraph boundary
        if end < len(text):
            # Look for natural break point within last 20% of chunk
            search_start = start + int(chunk_size * 0.8)
            search_text = text[search_start:end]

            # Prefer paragraph break, then sentence break, then word break
            for pattern in ['\n\n', '\n', '. ', '! ', '? ', ', ', ' ']:
                last_break = search_text.rfind(pattern)
                if last_break != -1:
                    end = search_start + last_break + len(pattern)
                    break

        chunk_text = text[start:end].strip()

        if chunk_text:  # Skip empty chunks
            chunks.append({
                "text": chunk_text,
                "index": index,
                "start": start,
                "end": min(end, len(text)),
            })
            index += 1

        # Move start with overlap
        start = end - overlap if end < len(text) else len(text)

    return chunks


def split_text_semantic(text: str) -> List[Dict[str, Any]]:
    """
    텍스트를 의미 단위로 분할 (Semantic Chunking)

    Algorithm:
    1. Split into sentences at `. `, `! `, `? `, newlines
    2. Detect topic boundaries: section headers, double newlines,
       significant vocabulary shift between consecutive sentences
    3. Group sentences into chunks at topic boundaries
    4. Target chunk size: 300-800 chars (flexible, never mid-sentence)

    Returns list of dicts with:
    - text: chunk content
    - index: chunk number (0-based)
    - start: character offset
    - end: character offset
    """
    TARGET_MIN = 300
    TARGET_MAX = 800

    # Regex for section headers: markdown headers, numbered sections, Roman numerals
    HEADER_RE = re.compile(
        r'^(?:#{1,6}\s|(?:[IVXivx]+\.|[0-9]+\.)\s)',
        re.MULTILINE
    )

    def is_header(sentence: str) -> bool:
        return bool(HEADER_RE.match(sentence.strip()))

    def vocabulary_shift(sent_a: str, sent_b: str) -> float:
        """
        Jaccard distance between word sets of two sentences.
        Returns 1.0 for completely different vocabularies, 0.0 for identical.
        """
        words_a = set(re.findall(r'\w+', sent_a.lower()))
        words_b = set(re.findall(r'\w+', sent_b.lower()))
        # Ignore very short stop-word-dominated sentences
        words_a -= {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'and', 'or',
                    'to', 'of', 'in', 'on', 'at', 'it', 'this', 'that', 'for'}
        words_b -= {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'and', 'or',
                    'to', 'of', 'in', 'on', 'at', 'it', 'this', 'that', 'for'}
        if not words_a or not words_b:
            return 0.0
        intersection = len(words_a & words_b)
        union = len(words_a | words_b)
        return 1.0 - (intersection / union) if union > 0 else 0.0

    def is_topic_boundary(prev: str, curr: str, preceded_by_double_newline: bool) -> bool:
        if is_header(curr):
            return True
        if preceded_by_double_newline:
            return True
        if vocabulary_shift(prev, curr) > 0.85:
            return True
        return False

    # ---- Step 1: Split text into (sentence, preceded_by_double_newline) pairs ----
    # Mark double-newline positions first, then flatten to sentences
    raw_segments = re.split(r'(\n\n+)', text)

    sentences: List[tuple] = []  # (sentence_text, preceded_by_double_newline)
    after_double_newline = False

    for seg in raw_segments:
        if re.match(r'\n\n+', seg):
            after_double_newline = True
            continue

        # Split segment into sentences
        # Use a lookahead to keep delimiters attached to the preceding sentence
        parts = re.split(r'(?<=[.!?])\s+', seg.strip())
        # Also split on single newlines within a segment
        sub_parts: List[str] = []
        for part in parts:
            sub_parts.extend(line.strip() for line in part.split('\n') if line.strip())

        for i, part in enumerate(sub_parts):
            if part:
                sentences.append((part, after_double_newline and i == 0))
        after_double_newline = False

    if not sentences:
        return []

    # ---- Step 2: Group sentences into chunks at topic boundaries ----
    chunks: List[Dict[str, Any]] = []
    current_group: List[str] = []
    current_len = 0
    index = 0

    # Track character offsets by rebuilding from the original text
    # We'll compute start/end by searching forward in the original text
    search_pos = 0  # current scan position in `text`

    def find_offset(needle: str, from_pos: int) -> int:
        """Find needle in text starting from from_pos, return start index."""
        pos = text.find(needle, from_pos)
        return pos if pos != -1 else from_pos

    def flush_group(group: List[str]) -> Optional[Dict[str, Any]]:
        """Turn accumulated sentences into a chunk dict."""
        nonlocal index, search_pos
        if not group:
            return None
        chunk_text = ' '.join(group).strip()
        if not chunk_text:
            return None
        start = find_offset(group[0], search_pos)
        # Advance search_pos past the last sentence
        last_sentence = group[-1]
        end_candidate = text.find(last_sentence, search_pos)
        if end_candidate != -1:
            end = end_candidate + len(last_sentence)
            search_pos = end
        else:
            end = start + len(chunk_text)
            search_pos = end
        chunk = {
            "text": chunk_text,
            "index": index,
            "start": start,
            "end": end,
        }
        index += 1
        return chunk

    for i, (sent, double_nl) in enumerate(sentences):
        prev_sent = sentences[i - 1][0] if i > 0 else ""

        at_boundary = (
            i > 0
            and is_topic_boundary(prev_sent, sent, double_nl)
        )

        if at_boundary and current_len >= TARGET_MIN:
            # Flush current group
            chunk = flush_group(current_group)
            if chunk:
                chunks.append(chunk)
            current_group = [sent]
            current_len = len(sent)
        elif current_len + len(sent) > TARGET_MAX and current_len >= TARGET_MIN:
            # Chunk is full enough — flush even without a boundary
            chunk = flush_group(current_group)
            if chunk:
                chunks.append(chunk)
            current_group = [sent]
            current_len = len(sent)
        else:
            current_group.append(sent)
            current_len += len(sent)

    # Flush remaining sentences
    if current_group:
        chunk = flush_group(current_group)
        if chunk:
            chunks.append(chunk)

    return chunks


# ============================================================
# 3. ONTOLOGY EXTRACTION (Rule-based, no LLM)
# ============================================================

# Predefined entity categories with Korean/English detection patterns
ENTITY_CATEGORIES = {
    "Person": {
        "ko_suffixes": ["교수", "박사", "대표", "원장", "장관", "위원", "연구원", "의원"],
        "en_patterns": [r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b"],  # First Last
    },
    "Organization": {
        "ko_suffixes": ["회사", "기업", "그룹", "재단", "협회", "학회", "연구소", "센터", "원", "부", "처", "청", "위원회", "공사"],
        "en_patterns": [r"\b[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*\s+(?:Inc|Corp|Ltd|Co|LLC|Foundation|Institute|Association|Group|Labs?)\b"],
    },
    "Technology": {
        "ko_keywords": ["기술", "플랫폼", "시스템", "알고리즘", "프로토콜", "엔진", "프레임워크", "아키텍처"],
        "en_patterns": [r"\b(?:AI|ML|IoT|API|SDK|GPU|CPU|NLP|LLM|CRISPR|PCR|mRNA|DNA|RNA)\b"],
    },
    "Institution": {
        "ko_suffixes": ["대학", "대학교", "병원", "의원", "학교"],
        "en_patterns": [r"\b[A-Z][A-Za-z]+\s+(?:University|College|Hospital|School|Academy)\b"],
    },
    "Product": {
        "ko_keywords": ["제품", "솔루션", "서비스", "앱", "키트", "장비", "장치", "디바이스"],
        "en_patterns": [r"\b[A-Z][A-Za-z]*[-]?[A-Z0-9]+[A-Za-z]*\b"],  # CamelCase / product names
    },
    "Regulation": {
        "ko_keywords": ["규제", "법률", "법안", "조례", "인증", "허가", "승인", "가이드라인", "지침"],
        "en_patterns": [r"\b(?:FDA|EMA|CE|ISO|GMP|GLP|GCP|KFDA|MFDS|IEC)\b"],
    },
    "Disease": {
        "ko_keywords": ["질환", "질병", "증후군", "암", "바이러스", "감염", "병변"],
        "en_patterns": [r"\b[A-Z][a-z]+(?:'s)?\s+(?:disease|syndrome|disorder|cancer|virus)\b"],
    },
    "Region": {
        "ko_keywords": ["시", "도", "군", "구", "국가", "지역"],
        "en_patterns": [r"\b(?:Korea|Japan|China|USA|EU|Europe|Asia|America)\b"],
    },
    "Chemical": {
        "ko_keywords": ["물질", "화합물", "성분", "단백질", "항체", "효소", "시약"],
        "en_patterns": [r"\b[A-Z][a-z]*(?:ase|ine|ide|ate|ol|yl)\b"],
    },
    "Method": {
        "ko_keywords": ["방법", "기법", "분석", "검사", "측정", "진단", "치료법", "공법"],
        "en_patterns": [r"\b[A-Z][A-Za-z]+\s+(?:method|assay|analysis|test|technique|therapy|imaging)\b"],
    },
}

# Predefined edge/relation types with Korean verb patterns
EDGE_TYPES = {
    "DEVELOPS": {
        "ko_verbs": ["개발", "만들", "구축", "설계", "제작"],
        "en_verbs": ["develop", "build", "create", "design", "engineer"],
    },
    "REGULATES": {
        "ko_verbs": ["규제", "허가", "승인", "인증", "관리", "감독"],
        "en_verbs": ["regulate", "approve", "certify", "authorize", "oversee"],
    },
    "COMPETES_WITH": {
        "ko_verbs": ["경쟁", "대항", "맞서"],
        "en_verbs": ["compete", "rival", "challenge"],
    },
    "TREATS": {
        "ko_verbs": ["치료", "진단", "검출", "탐지"],
        "en_verbs": ["treat", "diagnose", "detect", "cure", "target"],
    },
    "FUNDS": {
        "ko_verbs": ["투자", "지원", "출자", "펀딩"],
        "en_verbs": ["fund", "invest", "finance", "sponsor", "grant"],
    },
    "PARTNERS_WITH": {
        "ko_verbs": ["협력", "협업", "제휴", "파트너", "공동"],
        "en_verbs": ["partner", "collaborate", "cooperate", "ally", "joint"],
    },
    "ANALYZES": {
        "ko_verbs": ["분석", "연구", "조사", "평가", "검토"],
        "en_verbs": ["analyze", "research", "study", "evaluate", "assess"],
    },
    "DETECTS": {
        "ko_verbs": ["검출", "탐지", "발견", "식별", "감지"],
        "en_verbs": ["detect", "identify", "discover", "sense", "screen"],
    },
    "PRODUCES": {
        "ko_verbs": ["생산", "제조", "양산", "공급"],
        "en_verbs": ["produce", "manufacture", "supply", "fabricate"],
    },
    "APPROVES": {
        "ko_verbs": ["승인", "허가", "인가", "통과"],
        "en_verbs": ["approve", "authorize", "license", "clear", "pass"],
    },
}


def _count_entity_mentions(text: str, category: str, config: Dict) -> List[Dict[str, Any]]:
    """특정 entity 카테고리에 해당하는 멘션을 텍스트에서 찾아 반환"""
    mentions = []

    # Korean suffix-based detection
    for suffix_key in ("ko_suffixes", "ko_keywords"):
        for term in config.get(suffix_key, []):
            # Find words/phrases ending with or containing the keyword
            pattern = rf'[\w가-힣]+{re.escape(term)}'
            found = re.findall(pattern, text)
            for match in found:
                mentions.append(match)

    # English pattern-based detection
    for pat in config.get("en_patterns", []):
        found = re.findall(pat, text)
        for match in found:
            mentions.append(match)

    return mentions


def _count_edge_mentions(text: str, edge_type: str, config: Dict) -> int:
    """특정 edge 타입이 텍스트에 몇 번 등장하는지 카운트"""
    count = 0

    for verb in config.get("ko_verbs", []):
        # Korean: match verb stem (conjugation-tolerant via prefix matching)
        pattern = rf'{re.escape(verb)}[하한할함합했되된될됨됩]?'
        count += len(re.findall(pattern, text))

    for verb in config.get("en_verbs", []):
        # English: case-insensitive whole word match (with basic inflection)
        pattern = rf'\b{re.escape(verb)}(?:s|ed|ing|es|d)?\b'
        count += len(re.findall(pattern, text, re.IGNORECASE))

    return count


def extract_ontology(text: str, source_file: str) -> Dict[str, Any]:
    """
    텍스트에서 규칙 기반으로 온톨로지를 추출한다.

    순수 Python 규칙 기반 구현 (외부 LLM API 호출 없음):
    - Entity types: 텍스트 내 빈도 기반 상위 10개
    - Edge types: 텍스트 내 등장하는 관계 6-10개

    Returns:
        {
            "entity_types": [...],  # max 10
            "edge_types": [...],    # 6-10
            "source_file": str,
            "timestamp": str,
            "text_stats": {...}
        }
    """
    # --- Entity type extraction ---
    entity_results = []

    for category, config in ENTITY_CATEGORIES.items():
        mentions = _count_entity_mentions(text, category, config)
        if mentions:
            # Deduplicate and count
            mention_counts = Counter(mentions)
            top_examples = [m for m, _ in mention_counts.most_common(5)]
            total = sum(mention_counts.values())
            entity_results.append({
                "type": category,
                "mention_count": total,
                "examples": top_examples,
            })

    # Sort by mention count, take top 10
    entity_results.sort(key=lambda x: x["mention_count"], reverse=True)
    entity_types = entity_results[:10]

    # --- Edge type extraction ---
    edge_results = []

    for edge_type, config in EDGE_TYPES.items():
        count = _count_edge_mentions(text, edge_type, config)
        if count > 0:
            edge_results.append({
                "type": edge_type,
                "mention_count": count,
            })

    # Sort by mention count, take 6-10
    edge_results.sort(key=lambda x: x["mention_count"], reverse=True)
    # Ensure at least 6 if available, at most 10
    edge_types = edge_results[:10]
    # If fewer than 6 found, include all available
    if len(edge_types) < 6:
        edge_types = edge_results  # take whatever we have

    return {
        "entity_types": entity_types,
        "edge_types": edge_types,
        "source_file": source_file,
        "timestamp": datetime.now().isoformat(),
        "text_stats": {
            "total_chars": len(text),
            "total_words": len(text.split()),
        },
        "extraction_method": "rule-based (no LLM)",
    }


# ============================================================
# 4. MEMPALACE STORAGE (Uses mempalace CLI)
# ============================================================

def get_mempalace_cmd() -> str:
    """MemPalace CLI 경로"""
    # Check project venv first
    venv_path = Path(__file__).parent / "mp-env" / "bin" / "mempalace"
    if venv_path.exists():
        return str(venv_path)

    # Check system PATH
    import shutil
    cmd = shutil.which("mempalace")
    if cmd:
        return cmd

    return ""


def store_chunks_to_mempalace(
    chunks: List[Dict[str, Any]],
    wing: str,
    room: str,
    source_file: str,
    mempalace_cmd: str
) -> Dict[str, Any]:
    """청크를 MemPalace drawers로 저장 (디렉토리 기반 mine)"""
    import tempfile
    import shutil

    # Create a temp directory structure: wing/room/chunk_files
    tmpdir = tempfile.mkdtemp(
        prefix="muchanipo-",
        dir=os.environ.get('TMPDIR', '/tmp')
    )

    try:
        # Write each chunk as a separate text file
        for chunk in chunks:
            chunk_filename = f"{Path(source_file).stem}_chunk{chunk['index']+1:04d}.txt"
            chunk_path = os.path.join(tmpdir, chunk_filename)

            with open(chunk_path, 'w', encoding='utf-8') as f:
                header = f"[Source: {source_file} | Chunk: {chunk['index']+1}/{len(chunks)} | Chars: {chunk['start']}-{chunk['end']}]\n\n"
                f.write(header + chunk['text'])

        # Copy mempalace.yaml from initialized vault to temp dir
        vault_config = _runtime_paths.get_vault_path("mempalace.yaml")
        if vault_config.exists():
            import shutil as sh
            sh.copy2(vault_config, os.path.join(tmpdir, "mempalace.yaml"))

        _MEMPALACE_TIMEOUT = int(os.environ.get("MEMPALACE_TIMEOUT", "120"))
        # Mine the entire temp directory into mempalace
        result = subprocess.run(
            [mempalace_cmd, "mine", tmpdir, "--wing", wing],
            capture_output=True, text=True, timeout=_MEMPALACE_TIMEOUT
        )

        if result.returncode == 0:
            return {"stored": len(chunks), "failed": 0, "output": result.stdout}
        else:
            print(f"  WARNING: mine failed: {result.stderr[:200]}")
            return {"stored": 0, "failed": len(chunks), "error": result.stderr[:200]}

    except Exception as e:
        print(f"  ERROR: {str(e)[:200]}")
        return {"stored": 0, "failed": len(chunks), "error": str(e)[:200]}
    finally:
        # Cleanup temp directory
        shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# 4.5 WIKI PAGE MANAGEMENT (Karpathy LLM Wiki pattern)
# ============================================================

def _get_wiki_dir() -> Path:
    """wiki/ 디렉토리 경로 반환 (없으면 생성)"""
    wiki_dir = Path(__file__).parent / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    return wiki_dir


def _get_raw_dir() -> Path:
    """raw/ 디렉토리 경로 반환 (없으면 생성)"""
    raw_dir = Path(__file__).parent / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    return raw_dir


def _append_wiki_log(action: str, details: str, wiki_dir: Optional[Path] = None):
    """wiki/log.md에 감사 로그 append (절대 기존 내용 수정 안함)"""
    if wiki_dir is None:
        wiki_dir = _get_wiki_dir()
    log_path = wiki_dir / "log.md"

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"- {timestamp} | {action} | {details}\n"

    if not log_path.exists():
        log_path.write_text(
            "# MuchaNipo Wiki Log\n"
            "<!-- Append-only. 절대 수정하지 않고 추가만. -->\n\n"
            "## Operations\n"
            "<!-- 형식: - YYYY-MM-DD HH:MM | ACTION | details -->\n",
            encoding="utf-8"
        )

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(entry)


def _update_wiki_index(
    slug: str,
    topic: str,
    confidence: str,
    source_file: str,
    wiki_dir: Optional[Path] = None,
):
    """wiki/index.md 테이블에 새 페이지 메타데이터 추가/업데이트"""
    if wiki_dir is None:
        wiki_dir = _get_wiki_dir()
    index_path = wiki_dir / "index.md"

    updated = datetime.now().strftime("%Y-%m-%d")
    new_row = f"| [{slug}.md]({slug}.md) | {topic} | {updated} | {confidence} | {source_file} |"

    if not index_path.exists():
        index_path.write_text(
            "# MuchaNipo Wiki Index\n"
            "<!-- LLM이 자동 유지관리. 새 페이지 생성 시 여기에 추가. -->\n\n"
            "## Pages\n"
            "| Page | Topic | Updated | Confidence | Source |\n"
            "|------|-------|---------|------------|--------|\n",
            encoding="utf-8"
        )

    content = index_path.read_text(encoding="utf-8")

    # Check if this slug already has a row — update it
    slug_pattern = re.compile(rf'^\|.*\[{re.escape(slug)}\.md\].*$', re.MULTILINE)
    if slug_pattern.search(content):
        content = slug_pattern.sub(new_row, content)
        index_path.write_text(content, encoding="utf-8")
    else:
        # Append new row before the closing comment or at the end of the table
        # Find the last table row or the comment placeholder
        if "<!-- 아직 페이지 없음" in content:
            content = content.replace(
                "<!-- 아직 페이지 없음. 첫 인제스트 시 자동 추가됨. -->",
                new_row,
            )
        else:
            # Append after the last line that starts with '|'
            lines = content.split('\n')
            insert_idx = len(lines)
            for i in range(len(lines) - 1, -1, -1):
                if lines[i].startswith('|'):
                    insert_idx = i + 1
                    break
            lines.insert(insert_idx, new_row)
            content = '\n'.join(lines)
        index_path.write_text(content, encoding="utf-8")


def save_wiki_page(
    topic: str,
    content: str,
    source_file: str,
    wiki_dir: Path,
    confidence: str = "medium",
) -> Path:
    """
    인제스트 결과를 wiki/ 페이지로 저장.

    - slug 기반 파일명 생성
    - YAML frontmatter + content 작성
    - index.md 업데이트
    - log.md에 기록
    """
    slug = re.sub(r'[^a-z0-9\-]', '-', topic.lower().replace(' ', '-'))
    slug = re.sub(r'-+', '-', slug).strip('-')
    page_path = wiki_dir / f"{slug}.md"

    updated = datetime.now().strftime("%Y-%m-%d %H:%M")

    frontmatter = (
        f"---\n"
        f"topic: \"{topic}\"\n"
        f"source: \"{source_file}\"\n"
        f"confidence: \"{confidence}\"\n"
        f"created: \"{updated}\"\n"
        f"updated: \"{updated}\"\n"
        f"---\n\n"
    )

    page_content = frontmatter + f"# {topic}\n\n" + content

    page_path.write_text(page_content, encoding="utf-8")

    # Update index.md
    _update_wiki_index(slug, topic, confidence, source_file, wiki_dir)

    # Log the operation
    action = "UPDATE" if page_path.exists() else "CREATE"
    _append_wiki_log(action, f"Page '{slug}.md' from source '{source_file}'", wiki_dir)

    return page_path


def scan_raw_directory(
    raw_dir: Path,
    supported_extensions: tuple = ('.pdf', '.md', '.txt', '.html', '.json'),
) -> List[Path]:
    """raw/ 디렉토리의 인제스트 가능한 파일 목록 반환 (README.md 제외)"""
    files = []
    for f in sorted(raw_dir.iterdir()):
        if f.is_file() and f.suffix.lower() in supported_extensions:
            if f.name.lower() == 'readme.md':
                continue
            files.append(f)
    return files


# ============================================================
# 5. METADATA & REPORT
# ============================================================

def generate_ingest_report(
    file_path: str,
    text_stats: Dict,
    chunks: List[Dict],
    storage_result: Dict,
    wing: str,
    room: str,
    duration: float
) -> Dict[str, Any]:
    """인제스트 결과 리포트 생성"""
    report = {
        "timestamp": datetime.now().isoformat(),
        "source_file": os.path.basename(file_path),
        "source_path": file_path,
        "text_stats": text_stats,
        "chunking": {
            "total_chunks": len(chunks),
            "chunk_size": 500,
            "overlap": 50,
            "avg_chunk_length": sum(len(c["text"]) for c in chunks) / len(chunks) if chunks else 0,
        },
        "mempalace": {
            "wing": wing,
            "room": room,
            "stored": storage_result.get("stored", 0),
            "failed": storage_result.get("failed", 0),
        },
        "duration_seconds": round(duration, 2),
        "status": "success" if storage_result.get("failed", 0) == 0 else "partial",
        "next_steps": [
            "온톨로지 추출: --extract-ontology 플래그로 규칙 기반 추출 (내장)",
            "Claude: KG 트리플 생성 (Haiku 병렬) — 청크별 엔티티/관계",
            "Claude: Council 실행 — 페르소나가 mempalace_search로 원문 직접 검색",
        ]
    }
    return report


def get_text_stats(text: str) -> Dict:
    """텍스트 통계"""
    return {
        "total_chars": len(text),
        "total_lines": text.count('\n') + 1,
        "total_words": len(text.split()),
        "total_paragraphs": len(re.split(r'\n\s*\n', text)),
    }


# ============================================================
# 6. MODEL ROUTING TABLE (for Claude reference)
# ============================================================

MODEL_ROUTING = """
## MuchaNipo Model Routing (API Infrastructure)

| Task                    | Model              | Cost  | Notes                          |
|------------------------|--------------------|-------|--------------------------------|
| Text extraction        | Code (no model)    | $0    | This script                    |
| Chunking               | Code (no model)    | $0    | This script                    |
| MemPalace storage      | Code (no model)    | $0    | This script                    |
| Ontology extraction    | Code (rule-based)  | $0    | --extract-ontology flag         |
| Entity/relation extract| Haiku / Gemma4     | $     | 청크별 병렬, 대량 처리            |
| Persona generation     | Sonnet             | $$    | 창의적 + 구조적                  |
| Council debate         | Opus               | $$$   | 깊은 분석 필요 시                |
| Council debate (fast)  | Sonnet             | $$    | 속도 우선                       |
| Eval grading           | Haiku              | $     | 단순 점수 매기기                 |
| Wiki formatting        | Haiku              | $     | 템플릿 작업                     |
| Embedding              | nomic-embed-text   | $0    | Ollama 로컬                    |
| Long doc analysis      | Kimi / Gemini      | $$    | 100K+ 컨텍스트                  |
| Web research summary   | Sonnet / Kimi      | $$    | 정보 압축                       |
"""


# ============================================================
# SCAN-RAW MODE (Karpathy LLM Wiki: raw/ → wiki/ pipeline)
# ============================================================

def _ingest_single_file(
    file_path: Path,
    args,
    wiki_dir: Path,
) -> Optional[Dict[str, Any]]:
    """
    단일 파일 인제스트 → wiki 페이지 생성.
    기존 인제스트 로직을 재사용하되 wiki/ 연동을 추가한다.
    raw/ 파일은 절대 수정하지 않는다 (읽기만).

    Returns ingest result dict or None on failure.
    """
    file_str = str(file_path)
    filename = file_path.name

    print(f"\n  --- Ingesting: {filename} ---")

    # 1. Extract text (read-only on raw file)
    text = extract_text(file_str)
    if not text:
        print(f"    SKIP: No text extracted from {filename}")
        _append_wiki_log("SKIP", f"No text extracted from '{filename}'", wiki_dir)
        return None

    # 2. Preprocess
    text = preprocess_text(text)
    stats = get_text_stats(text)
    print(f"    {stats['total_chars']:,} chars, {stats['total_words']:,} words")

    # 3. Chunk
    if args.strategy == "semantic":
        chunks = split_text_semantic(text)
    else:
        chunks = split_text_into_chunks(text, args.chunk_size, args.overlap)
    print(f"    {len(chunks)} chunks generated")

    # 4. Generate topic from filename
    topic = file_path.stem.replace('-', ' ').replace('_', ' ').title()

    # 5. Build wiki page content from chunks
    page_sections = []
    for chunk in chunks:
        page_sections.append(chunk["text"])
    page_content = "\n\n".join(page_sections)

    # 6. Extract ontology if requested
    confidence = "medium"
    ontology = None
    if args.extract_ontology:
        ontology = extract_ontology(text, filename)
        entity_count = len(ontology.get("entity_types", []))
        edge_count = len(ontology.get("edge_types", []))
        print(f"    Ontology: {entity_count} entity types, {edge_count} edge types")
        # Higher entity/edge counts → higher confidence
        if entity_count >= 5 and edge_count >= 3:
            confidence = "high"
        elif entity_count <= 1:
            confidence = "low"

    # 7. Save wiki page
    if not args.dry_run:
        page_path = save_wiki_page(
            topic=topic,
            content=page_content,
            source_file=filename,
            wiki_dir=wiki_dir,
            confidence=confidence,
        )
        print(f"    Wiki page: {page_path.name}")
    else:
        print(f"    [DRY RUN] Would create wiki page: {topic}")

    # 8. Store to MemPalace (if available and not dry-run)
    storage_result = {"stored": 0, "failed": 0}
    if not args.dry_run:
        mempalace_cmd = get_mempalace_cmd()
        if mempalace_cmd:
            room = file_path.stem.lower().replace(' ', '-')
            storage_result = store_chunks_to_mempalace(
                chunks, args.wing, room, filename, mempalace_cmd
            )
            print(f"    MemPalace: stored={storage_result['stored']}, failed={storage_result['failed']}")
        else:
            # Fallback: save chunks as JSON
            log_dir = Path(__file__).parent / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            output_path = log_dir / f"ingest-{file_path.stem}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump({"source": file_str, "chunks": chunks, "stats": stats}, f, ensure_ascii=False, indent=2)
            print(f"    Chunks saved: {output_path}")
            storage_result = {"stored": 0, "failed": 0, "fallback": "json"}

    return {
        "file": filename,
        "topic": topic,
        "stats": stats,
        "chunks_count": len(chunks),
        "confidence": confidence,
        "storage": storage_result,
        "ontology": ontology,
    }


def _run_scan_raw(args):
    """--scan-raw 모드: raw/ 디렉토리의 모든 파일을 스캔하여 인제스트 → wiki/ 생성"""
    raw_dir = _get_raw_dir()
    wiki_dir = _get_wiki_dir()

    print(f"\n{'='*60}")
    print(f"  MuchaNipo Scan-Raw Mode (Karpathy LLM Wiki)")
    print(f"{'='*60}")
    print(f"\n  Raw dir:  {raw_dir}")
    print(f"  Wiki dir: {wiki_dir}")

    # Scan raw/ for supported files
    files = scan_raw_directory(raw_dir)

    if not files:
        print(f"\n  No files found in raw/. Drop PDF, MD, TXT, HTML, or JSON files there.")
        _append_wiki_log("SCAN", "No files found in raw/", wiki_dir)
        return

    print(f"\n  Found {len(files)} file(s) to ingest:")
    for f in files:
        print(f"    - {f.name} ({f.stat().st_size / 1024:.1f} KB)")

    start_time = datetime.now()
    results = []

    for file_path in files:
        result = _ingest_single_file(file_path, args, wiki_dir)
        if result:
            results.append(result)

    duration = (datetime.now() - start_time).total_seconds()

    # Log summary
    _append_wiki_log(
        "SCAN_RAW",
        f"Processed {len(results)}/{len(files)} files in {duration:.1f}s",
        wiki_dir,
    )

    # Save batch report
    if not args.dry_run:
        report_dir = Path(__file__).parent / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"scan-raw-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "mode": "scan-raw",
                "files_found": len(files),
                "files_ingested": len(results),
                "duration_seconds": round(duration, 2),
                "results": results,
            }, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n  Report: {report_path}")

    # Summary
    print(f"\n{'─'*60}")
    print(f"  DONE in {duration:.1f}s")
    print(f"  {len(results)}/{len(files)} files ingested → wiki/")
    print(f"  Wiki index: {wiki_dir / 'index.md'}")
    print(f"  Wiki log:   {wiki_dir / 'log.md'}")
    print(f"{'─'*60}\n")


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="MuchaNipo Document Ingest Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=MODEL_ROUTING
    )
    parser.add_argument("file", nargs="?", default=None, help="File to ingest (PDF, TXT, MD, HTML). Optional when --scan-raw is used.")
    parser.add_argument("--chunk-size", type=int, default=500, help="Chunk size in characters (default: 500)")
    parser.add_argument("--overlap", type=int, default=50, help="Chunk overlap in characters (default: 50)")
    parser.add_argument("--wing", default="general", help="MemPalace wing name (default: general)")
    parser.add_argument("--room", default="general", help="MemPalace room name (default: general)")
    parser.add_argument(
        "--strategy",
        choices=["recursive", "semantic"],
        default="recursive",
        help="Chunking strategy: recursive (default, 500-char) or semantic (topic-aware, 300-800 chars)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview chunks without storing")
    parser.add_argument("--extract-ontology", action="store_true", help="Extract ontology (entity/edge types) from text using rule-based patterns")
    parser.add_argument("--scan-raw", action="store_true",
        help="Scan .omc/autoresearch/raw/ directory and ingest all files")
    parser.add_argument("--output", help="Save report to JSON file")

    args = parser.parse_args()

    # --scan-raw mode: batch ingest from raw/ directory
    if args.scan_raw:
        _run_scan_raw(args)
        return

    # Validate input for single-file mode
    if args.file is None:
        parser.error("file is required unless --scan-raw is used")
    if not os.path.exists(args.file):
        print(f"ERROR: File not found: {args.file}")
        sys.exit(1)

    start_time = datetime.now()

    # Step 1: Extract text
    print(f"\n{'='*60}")
    print(f"  MuchaNipo Document Ingest")
    print(f"{'='*60}")
    print(f"\n  File: {os.path.basename(args.file)}")
    print(f"  Size: {os.path.getsize(args.file) / 1024:.1f} KB")

    print(f"\n  [1/4] Extracting text...")
    text = extract_text(args.file)
    if not text:
        print("  ERROR: No text extracted. Check file format.")
        sys.exit(1)

    # Step 2: Preprocess
    print(f"  [2/4] Preprocessing...")
    text = preprocess_text(text)
    stats = get_text_stats(text)
    print(f"         {stats['total_chars']:,} chars, {stats['total_words']:,} words, {stats['total_paragraphs']} paragraphs")

    # Step 3: Chunk
    if args.strategy == "semantic":
        print(f"  [3/4] Chunking (semantic, target 300-800 chars)...")
        chunks = split_text_semantic(text)
    else:
        print(f"  [3/4] Chunking (recursive, {args.chunk_size} chars, {args.overlap} overlap)...")
        chunks = split_text_into_chunks(text, args.chunk_size, args.overlap)
    print(f"         {len(chunks)} chunks generated")

    # Step 3.5: Extract ontology (if requested, runs after chunking, before storage)
    ontology_path = None
    if args.extract_ontology:
        print(f"\n  [3.5/4] Extracting ontology (rule-based)...")
        ontology = extract_ontology(text, os.path.basename(args.file))
        print(f"         Entity types: {len(ontology['entity_types'])}, Edge types: {len(ontology['edge_types'])}")

        # Save ontology JSON to logs/
        ontology_filename = f"ontology-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        ontology_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
        os.makedirs(ontology_dir, exist_ok=True)
        ontology_path = os.path.join(ontology_dir, ontology_filename)
        with open(ontology_path, 'w', encoding='utf-8') as f:
            json.dump(ontology, f, ensure_ascii=False, indent=2)
        print(f"         Ontology saved: {ontology_path}")

        # Preview entity/edge types
        for et in ontology["entity_types"][:5]:
            examples_str = ", ".join(et["examples"][:3])
            print(f"           {et['type']}: {et['mention_count']} mentions ({examples_str})")
        if len(ontology["entity_types"]) > 5:
            print(f"           ... and {len(ontology['entity_types']) - 5} more entity types")
        for ed in ontology["edge_types"][:5]:
            print(f"           {ed['type']}: {ed['mention_count']} mentions")

    if args.dry_run:
        print(f"\n  --- DRY RUN: Preview first 3 chunks ---")
        for chunk in chunks[:3]:
            print(f"\n  [Chunk {chunk['index']+1}] ({len(chunk['text'])} chars)")
            print(f"  {chunk['text'][:200]}...")
        print(f"\n  Total: {len(chunks)} chunks would be stored")
        print(f"  Wing: {args.wing}, Room: {args.room}")
        if ontology_path:
            print(f"  Ontology: {ontology_path}")
        return

    # Step 4: Store to MemPalace
    mempalace_cmd = get_mempalace_cmd()
    if not mempalace_cmd:
        print("  WARNING: MemPalace CLI not found. Saving chunks as JSON instead.")
        # Fallback: save chunks as JSON
        output_path = args.output or f".omc/autoresearch/logs/ingest-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump({
                "source": args.file,
                "chunks": chunks,
                "stats": stats,
            }, f, ensure_ascii=False, indent=2)
        print(f"  Chunks saved to: {output_path}")
        storage_result = {"stored": 0, "failed": 0, "fallback": "json"}
    else:
        print(f"  [4/4] Storing to MemPalace (wing={args.wing}, room={args.room})...")
        storage_result = store_chunks_to_mempalace(
            chunks, args.wing, args.room,
            os.path.basename(args.file), mempalace_cmd
        )
        print(f"         Stored: {storage_result['stored']}, Failed: {storage_result['failed']}")

    # Generate report
    duration = (datetime.now() - start_time).total_seconds()
    report = generate_ingest_report(
        args.file, stats, chunks, storage_result,
        args.wing, args.room, duration
    )

    # Add ontology path to report if extracted
    if ontology_path:
        report["ontology"] = {
            "path": ontology_path,
            "entity_types_count": len(ontology["entity_types"]),
            "edge_types_count": len(ontology["edge_types"]),
        }

    # Save report
    report_path = args.output or f".omc/autoresearch/logs/ingest-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Summary
    print(f"\n{'─'*60}")
    print(f"  DONE in {duration:.1f}s")
    print(f"  {len(chunks)} chunks → MemPalace ({args.wing}/{args.room})")
    if ontology_path:
        print(f"  Ontology: {ontology_path}")
    print(f"  Report: {report_path}")
    print(f"\n  Next: KG 트리플 생성 (Haiku 병렬) → Council 실행")
    print(f"  Model routing: Haiku(엔티티) → Opus(Council)")
    print(f"{'─'*60}\n")


if __name__ == "__main__":
    main()
