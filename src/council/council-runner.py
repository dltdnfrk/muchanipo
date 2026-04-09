#!/usr/bin/env python3
"""
MuchaNipo CouncilRunner — 다중 페르소나 토론 자동화 오케스트레이터
Usage:
  python3 council-runner.py --topic "주제"
  python3 council-runner.py --topic "주제" --ontology logs/ontology-xxx.json
  python3 council-runner.py --topic "주제" --personas 5 --max-rounds 3
  python3 council-runner.py --topic "주제" --output council-report.json

구조:
  1. 페르소나 자동 생성 (온톨로지 기반 또는 기본 풀에서 선택)
  2. Round 1 — 각 페르소나의 독립 분석 프롬프트 파일 생성
  3. Round 2+ — 이전 라운드 결과 기반 교차 평가 프롬프트 생성
  4. 합의 측정 및 최종 Council Report JSON 생성

NOTE: 이 스크립트는 프롬프트를 생성하는 오케스트레이터.
      실제 LLM 호출은 Claude Code의 Agent tool이 담당.
      결과는 council-logs/{council_id}/round-{N}-{persona}.json에 저장됨.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 경로 설정
# ---------------------------------------------------------------------------

_BASE_DIR = Path(__file__).parent
_COUNCIL_LOGS_DIR = _BASE_DIR / "council-logs"
_CONFIG_PATH = _BASE_DIR / "config.json"


def _load_config() -> dict[str, Any]:
    """config.json 로드. 없으면 기본값 반환."""
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "council": {
            "max_rounds": 5,
            "convergence_threshold": 0.7,
            "persona_range": [3, 7],
        }
    }


# ---------------------------------------------------------------------------
# 페르소나 풀 정의
# ---------------------------------------------------------------------------

_PERSONA_POOL: list[dict[str, Any]] = [
    {
        "name": "이준혁",
        "role": "투자자",
        "expertise": ["벤처캐피털", "스타트업 생태계", "ROI 분석", "시장 규모"],
        "perspective_bias": "수익성과 확장 가능성 중심. 시장 규모와 투자 회수 가능성 우선 평가.",
        "argument_style": "데이터 기반, 회의적, 숫자로 검증 요구",
    },
    {
        "name": "박서연",
        "role": "기술전문가",
        "expertise": ["소프트웨어 아키텍처", "AI/ML", "시스템 설계", "기술 실현 가능성"],
        "perspective_bias": "기술적 타당성과 구현 난이도 중심. 과도한 낙관론에 비판적.",
        "argument_style": "분석적, 구현 세부사항 집중, 기술 부채 경고",
    },
    {
        "name": "김민지",
        "role": "사용자대표",
        "expertise": ["UX 리서치", "고객 인터뷰", "사용성 테스트", "고객 여정"],
        "perspective_bias": "실제 사용자 관점. 편의성, 직관성, 실생활 적용 가능성 우선.",
        "argument_style": "공감적, 사용 시나리오 중심, 현장 경험 강조",
    },
    {
        "name": "최동원",
        "role": "규제전문가",
        "expertise": ["법률 규정", "인증/허가", "컴플라이언스", "리스크 관리"],
        "perspective_bias": "규제 리스크와 법적 준수 중심. 빠른 출시보다 안전 우선.",
        "argument_style": "보수적, 규정 인용, 잠재 리스크 열거",
    },
    {
        "name": "신예린",
        "role": "경쟁분석가",
        "expertise": ["경쟁사 분석", "시장 포지셔닝", "차별화 전략", "산업 트렌드"],
        "perspective_bias": "경쟁 구도와 차별화 포인트 중심. 유사 제품 대비 우위 검증 요구.",
        "argument_style": "비교 분석, 벤치마크 활용, 대안 제시",
    },
    {
        "name": "오태민",
        "role": "학술연구자",
        "expertise": ["학술 문헌", "방법론", "검증된 이론", "재현 가능성"],
        "perspective_bias": "근거 기반 접근. 검증되지 않은 주장에 회의적, 연구 방법론 중시.",
        "argument_style": "엄밀, 출처 요구, 가설과 검증 구분",
    },
    {
        "name": "한소희",
        "role": "시장분석가",
        "expertise": ["시장 조사", "소비자 행동", "수요 예측", "가격 전략"],
        "perspective_bias": "시장 타이밍과 수요 측면 중심. 현재 시장 상황과 트렌드 분석.",
        "argument_style": "통계 활용, 트렌드 패턴 분석, 시장 사이클 관점",
    },
]

# 온톨로지 entity_type → 페르소나 역할 매핑
_ENTITY_TYPE_TO_ROLE: dict[str, str] = {
    "technology": "기술전문가",
    "product": "경쟁분석가",
    "market": "시장분석가",
    "regulation": "규제전문가",
    "investment": "투자자",
    "user": "사용자대표",
    "research": "학술연구자",
    "competitor": "경쟁분석가",
    "business": "시장분석가",
    "science": "학술연구자",
    "organization": "투자자",
    "person": "사용자대표",
}


# ---------------------------------------------------------------------------
# 페르소나 선택 로직
# ---------------------------------------------------------------------------

def _select_personas_from_ontology(
    ontology_path: Path, count: int
) -> list[dict[str, Any]]:
    """온톨로지 JSON에서 entity_types를 읽어 관련 페르소나를 선택."""
    with open(ontology_path, "r", encoding="utf-8") as f:
        ontology = json.load(f)

    # entity_types 추출 (다양한 구조 지원)
    entity_types: list[str] = []
    if isinstance(ontology, dict):
        if "entity_types" in ontology:
            raw = ontology["entity_types"]
            if isinstance(raw, list):
                entity_types = [str(e).lower() for e in raw]
            elif isinstance(raw, dict):
                entity_types = [str(k).lower() for k in raw.keys()]
        elif "entities" in ontology:
            for ent in ontology.get("entities", []):
                if isinstance(ent, dict) and "type" in ent:
                    t = str(ent["type"]).lower()
                    if t not in entity_types:
                        entity_types.append(t)
    elif isinstance(ontology, list):
        for item in ontology:
            if isinstance(item, dict) and "type" in item:
                t = str(item["type"]).lower()
                if t not in entity_types:
                    entity_types.append(t)

    # entity_type → 역할 매핑
    preferred_roles: list[str] = []
    for et in entity_types:
        for key, role in _ENTITY_TYPE_TO_ROLE.items():
            if key in et or et in key:
                if role not in preferred_roles:
                    preferred_roles.append(role)

    # 선호 역할 우선 정렬
    selected: list[dict[str, Any]] = []
    used_roles: set[str] = set()

    for role in preferred_roles:
        for persona in _PERSONA_POOL:
            if persona["role"] == role and persona["role"] not in used_roles:
                selected.append(persona)
                used_roles.add(persona["role"])
                break
        if len(selected) >= count:
            break

    # 부족하면 나머지 풀에서 보충
    for persona in _PERSONA_POOL:
        if len(selected) >= count:
            break
        if persona["role"] not in used_roles:
            selected.append(persona)
            used_roles.add(persona["role"])

    return selected[:count]


def _select_personas_default(count: int) -> list[dict[str, Any]]:
    """기본 페르소나 풀에서 균형 있게 선택."""
    # 핵심 역할 우선: 투자자, 기술전문가, 사용자대표, 시장분석가 순
    priority_roles = ["투자자", "기술전문가", "사용자대표", "시장분석가", "경쟁분석가", "규제전문가", "학술연구자"]
    selected = []
    used_roles: set[str] = set()

    for role in priority_roles:
        if len(selected) >= count:
            break
        for persona in _PERSONA_POOL:
            if persona["role"] == role and persona["role"] not in used_roles:
                selected.append(persona)
                used_roles.add(persona["role"])
                break

    return selected[:count]


# ---------------------------------------------------------------------------
# 프롬프트 생성
# ---------------------------------------------------------------------------

_ROUND1_PROMPT_TEMPLATE = """\
# Council 토론 Round 1 — 독립 분석

## 당신의 역할
- 이름: {name}
- 역할: {role}
- 전문 분야: {expertise}
- 관점: {perspective_bias}
- 논증 스타일: {argument_style}

## 토론 주제
{topic}

## 지시사항

당신은 위 역할을 맡은 전문가입니다. 토론 주제를 **독립적으로** 분석하세요.

### 필수 수행 절차

1. **MemPalace 검색** (mcp__mempalace__mempalace_search 사용):
   - 토론 주제와 관련된 키워드로 최소 2회 검색
   - 당신의 전문 분야에서 관련 정보 탐색
   - 검색 결과를 분석에 활용

2. **당신의 관점에서 분석**:
   - 주제의 핵심 쟁점 식별
   - 찬성/우려 사항 각각 제시
   - 당신의 전문성 기반으로 판단

3. **결과 파일 저장** 형식:
```json
{{
  "council_id": "{council_id}",
  "round": 1,
  "persona": "{name}",
  "role": "{role}",
  "position": "찬성|반대|조건부찬성|중립",
  "analysis": "주요 분석 내용 (3-5문장)",
  "key_points": ["핵심 포인트 1", "핵심 포인트 2", "핵심 포인트 3"],
  "concerns": ["우려사항 1", "우려사항 2"],
  "evidence": ["mempalace 검색 출처 또는 근거 1", "근거 2"],
  "confidence": 0.0,
  "mempalace_queries": ["사용한 검색 쿼리 1", "검색 쿼리 2"]
}}
```

**confidence**: 0.0~1.0 범위. 근거가 충분하면 높게, 불확실하면 낮게 설정.

결과를 다음 경로에 저장하세요: `{output_path}`
"""

_ROUND_N_PROMPT_TEMPLATE = """\
# Council 토론 Round {round_num} — 교차 평가

## 당신의 역할
- 이름: {name}
- 역할: {role}
- 전문 분야: {expertise}
- 관점: {perspective_bias}
- 논증 스타일: {argument_style}

## 토론 주제
{topic}

## 이전 라운드 분석 결과

{previous_results_summary}

## 지시사항

위 다른 페르소나들의 분석을 검토하고 **교차 평가**를 수행하세요.

### 필수 수행 절차

1. **이전 라운드 결과 검토**:
   - 각 페르소나의 주장 분석
   - 동의 가능한 포인트 식별
   - 반박할 포인트 식별
   - 보완이 필요한 관점 파악

2. **MemPalace 추가 검색** (필요 시):
   - 반박 또는 보완을 위한 추가 근거 탐색
   - mcp__mempalace__mempalace_search 활용

3. **당신의 업데이트된 입장 정리**:
   - 이전 라운드 대비 입장 변화 여부
   - 새로운 합의 도출 여부
   - 남은 쟁점 명시

4. **결과 파일 저장** 형식:
```json
{{
  "council_id": "{council_id}",
  "round": {round_num},
  "persona": "{name}",
  "role": "{role}",
  "position": "찬성|반대|조건부찬성|중립",
  "agreements": ["동의하는 포인트 1", "포인트 2"],
  "rebuttals": [
    {{"target_persona": "대상 이름", "point": "반박 내용"}}
  ],
  "updated_analysis": "업데이트된 분석 (2-4문장)",
  "remaining_concerns": ["남은 우려사항"],
  "evidence": ["추가 근거"],
  "confidence": 0.0,
  "position_changed": false
}}
```

결과를 다음 경로에 저장하세요: `{output_path}`
"""


def _generate_round1_prompts(
    topic: str,
    personas: list[dict[str, Any]],
    council_id: str,
    council_dir: Path,
) -> list[Path]:
    """Round 1 프롬프트 파일들 생성."""
    prompt_files: list[Path] = []

    for persona in personas:
        persona_slug = persona["name"].replace(" ", "_")
        output_path = council_dir / f"round-1-{persona_slug}.json"
        prompt_path = council_dir / f"prompt-round-1-{persona_slug}.md"

        prompt = _ROUND1_PROMPT_TEMPLATE.format(
            name=persona["name"],
            role=persona["role"],
            expertise=", ".join(persona["expertise"]),
            perspective_bias=persona["perspective_bias"],
            argument_style=persona["argument_style"],
            topic=topic,
            council_id=council_id,
            output_path=str(output_path),
        )

        with open(prompt_path, "w", encoding="utf-8") as f:
            f.write(prompt)

        prompt_files.append(prompt_path)

    return prompt_files


def _generate_roundN_prompts(
    topic: str,
    personas: list[dict[str, Any]],
    council_id: str,
    council_dir: Path,
    round_num: int,
    previous_results: list[dict[str, Any]],
) -> list[Path]:
    """Round N (2+) 교차 평가 프롬프트 파일들 생성."""
    prompt_files: list[Path] = []

    # 이전 라운드 결과 요약 텍스트
    prev_summary_lines = []
    for res in previous_results:
        persona_name = res.get("persona", "알 수 없음")
        role = res.get("role", "")
        position = res.get("position", "")
        analysis = res.get("analysis", res.get("updated_analysis", ""))
        key_points = res.get("key_points", [])
        confidence = res.get("confidence", 0.0)

        prev_summary_lines.append(f"### {persona_name} ({role})")
        prev_summary_lines.append(f"- **입장**: {position}")
        prev_summary_lines.append(f"- **confidence**: {confidence:.2f}")
        if analysis:
            prev_summary_lines.append(f"- **분석**: {analysis}")
        if key_points:
            for kp in key_points:
                prev_summary_lines.append(f"  - {kp}")
        prev_summary_lines.append("")

    previous_results_summary = "\n".join(prev_summary_lines)

    for persona in personas:
        persona_slug = persona["name"].replace(" ", "_")
        output_path = council_dir / f"round-{round_num}-{persona_slug}.json"
        prompt_path = council_dir / f"prompt-round-{round_num}-{persona_slug}.md"

        prompt = _ROUND_N_PROMPT_TEMPLATE.format(
            name=persona["name"],
            role=persona["role"],
            expertise=", ".join(persona["expertise"]),
            perspective_bias=persona["perspective_bias"],
            argument_style=persona["argument_style"],
            topic=topic,
            council_id=council_id,
            round_num=round_num,
            previous_results_summary=previous_results_summary,
            output_path=str(output_path),
        )

        with open(prompt_path, "w", encoding="utf-8") as f:
            f.write(prompt)

        prompt_files.append(prompt_path)

    return prompt_files


# ---------------------------------------------------------------------------
# 결과 수집 및 합의 측정
# ---------------------------------------------------------------------------

def _collect_round_results(
    council_dir: Path,
    round_num: int,
    personas: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """특정 라운드의 결과 파일들을 수집."""
    results = []
    for persona in personas:
        persona_slug = persona["name"].replace(" ", "_")
        result_path = council_dir / f"round-{round_num}-{persona_slug}.json"
        if result_path.exists():
            with open(result_path, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                    results.append(data)
                except json.JSONDecodeError:
                    pass
    return results


def _measure_consensus(results: list[dict[str, Any]]) -> tuple[float, str]:
    """
    결과 리스트에서 합의 수준을 측정.

    Returns:
        (avg_confidence, consensus_description)
    """
    if not results:
        return 0.0, "결과 없음"

    confidences = [r.get("confidence", 0.0) for r in results]
    avg_confidence = sum(confidences) / len(confidences)

    # 입장 분포
    positions: dict[str, int] = {}
    for r in results:
        pos = r.get("position", "중립")
        positions[pos] = positions.get(pos, 0) + 1

    # 다수 입장
    dominant_position = max(positions, key=lambda k: positions[k])
    dominant_count = positions[dominant_position]
    total = len(results)

    if dominant_count == total:
        consensus_desc = f"완전 합의: 모든 페르소나 '{dominant_position}'"
    elif dominant_count >= total * 0.7:
        consensus_desc = f"강한 합의: {dominant_count}/{total} '{dominant_position}'"
    elif dominant_count >= total * 0.5:
        consensus_desc = f"부분 합의: {dominant_count}/{total} '{dominant_position}'"
    else:
        consensus_desc = f"의견 분산: {dict(positions)}"

    return avg_confidence, consensus_desc


# ---------------------------------------------------------------------------
# 오케스트레이션 상태 파일
# ---------------------------------------------------------------------------

_ORCHESTRATION_TEMPLATE = """\
# Council 오케스트레이션 가이드

## Council ID: {council_id}
## 주제: {topic}
## 생성 시각: {timestamp}

---

## 실행 순서

이 파일은 Claude Code(상위 오케스트레이터)가 Council을 단계별로 실행하기 위한 가이드입니다.

### Round 1 실행

다음 프롬프트 파일들을 **병렬로** 각 Agent에게 실행시키세요:

{round1_files}

각 Agent는 결과를 해당 JSON 파일에 저장합니다.

### Round 2+ 실행

Round 1 완료 후, council-runner.py를 `--resume` 모드로 실행하면
교차 평가 프롬프트가 생성됩니다:

```bash
python3 council-runner.py --resume {council_id}
```

또는 수동으로 Round 2 프롬프트 파일 실행:
{round2_placeholder}

### 최종 리포트

모든 라운드 완료 후:
```bash
python3 council-runner.py --finalize {council_id}
```

---

## 페르소나 목록

{personas_list}
"""


def _write_orchestration_guide(
    council_dir: Path,
    council_id: str,
    topic: str,
    personas: list[dict[str, Any]],
    round1_prompt_files: list[Path],
    timestamp: str,
) -> Path:
    """오케스트레이션 가이드 파일 생성."""
    round1_files_text = "\n".join(
        f"- `{pf}`" for pf in round1_prompt_files
    )

    personas_list_lines = []
    for p in personas:
        personas_list_lines.append(
            f"- **{p['name']}** ({p['role']}): {', '.join(p['expertise'][:2])}"
        )
    personas_list_text = "\n".join(personas_list_lines)

    guide_content = _ORCHESTRATION_TEMPLATE.format(
        council_id=council_id,
        topic=topic,
        timestamp=timestamp,
        round1_files=round1_files_text,
        round2_placeholder="(Round 1 완료 후 자동 생성됩니다)",
        personas_list=personas_list_text,
    )

    guide_path = council_dir / "ORCHESTRATION.md"
    with open(guide_path, "w", encoding="utf-8") as f:
        f.write(guide_content)

    return guide_path


# ---------------------------------------------------------------------------
# Council Report 생성
# ---------------------------------------------------------------------------

def _generate_council_report(
    topic: str,
    council_id: str,
    personas: list[dict[str, Any]],
    all_round_results: dict[int, list[dict[str, Any]]],
    total_rounds: int,
    timestamp: str,
) -> dict[str, Any]:
    """최종 Council Report JSON 생성."""
    # 마지막 라운드 결과 기준
    last_round_results = all_round_results.get(total_rounds, [])
    avg_confidence, consensus_desc = _measure_consensus(last_round_results)

    # 전체 evidence 수집
    all_evidence: list[str] = []
    for round_results in all_round_results.values():
        for r in round_results:
            for ev in r.get("evidence", []):
                if ev and ev not in all_evidence:
                    all_evidence.append(ev)

    # 합의 내용 (찬성/조건부찬성 다수의 key_points 종합)
    consensus_points: list[str] = []
    dissent_points: list[str] = []

    for r in last_round_results:
        pos = r.get("position", "중립")
        if pos in ("찬성", "조건부찬성"):
            for kp in r.get("key_points", []):
                if kp not in consensus_points:
                    consensus_points.append(kp)
        elif pos == "반대":
            for concern in r.get("concerns", r.get("remaining_concerns", [])):
                if concern not in dissent_points:
                    dissent_points.append(concern)

    # 권고사항: 조건부찬성의 우려사항 + 합의 포인트 기반
    recommendations: list[str] = []
    for r in last_round_results:
        for concern in r.get("concerns", r.get("remaining_concerns", [])):
            rec = f"[{r.get('role', '')}] {concern} 검토 필요"
            if rec not in recommendations:
                recommendations.append(rec)

    # 페르소나별 요약
    persona_summaries = []
    for r in last_round_results:
        persona_summaries.append({
            "name": r.get("persona", ""),
            "role": r.get("role", ""),
            "confidence": r.get("confidence", 0.0),
            "position": r.get("position", ""),
        })

    # 결과가 없는 페르소나는 기본값으로 채움
    existing_names = {ps["name"] for ps in persona_summaries}
    for persona in personas:
        if persona["name"] not in existing_names:
            persona_summaries.append({
                "name": persona["name"],
                "role": persona["role"],
                "confidence": 0.0,
                "position": "미응답",
            })

    return {
        "topic": topic,
        "council_id": council_id,
        "consensus": consensus_desc + (
            ". 주요 합의: " + "; ".join(consensus_points[:3]) if consensus_points else ""
        ),
        "dissent": "; ".join(dissent_points[:3]) if dissent_points else "반론 없음",
        "evidence": all_evidence[:10],
        "recommendations": recommendations[:5],
        "confidence": round(avg_confidence, 3),
        "personas": persona_summaries,
        "rounds": total_rounds,
        "timestamp": timestamp,
    }


# ---------------------------------------------------------------------------
# 메인 오케스트레이션 흐름
# ---------------------------------------------------------------------------

def run_council(
    topic: str,
    ontology_path: Path | None,
    persona_count: int,
    max_rounds: int,
    output_path: Path | None,
    resume_council_id: str | None,
    finalize_council_id: str | None,
) -> None:
    """Council 전체 오케스트레이션 실행."""
    config = _load_config()
    council_config = config.get("council", {})

    # 설정값 오버라이드
    convergence_threshold = council_config.get("convergence_threshold", 0.7)
    persona_range = council_config.get("persona_range", [3, 7])
    persona_count = max(persona_range[0], min(persona_range[1], persona_count))
    max_rounds = max_rounds or council_config.get("max_rounds", 5)

    # --finalize 모드
    if finalize_council_id:
        _finalize_council(finalize_council_id, output_path)
        return

    # --resume 모드
    if resume_council_id:
        _resume_council(resume_council_id, topic, max_rounds, convergence_threshold, output_path)
        return

    # 신규 Council 시작
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    council_id = f"council-{timestamp}"

    _COUNCIL_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    council_dir = _COUNCIL_LOGS_DIR / council_id
    council_dir.mkdir(parents=True, exist_ok=True)

    print(f"[CouncilRunner] Council 시작: {council_id}")
    print(f"[CouncilRunner] 주제: {topic}")

    # 페르소나 선택
    if ontology_path and ontology_path.exists():
        print(f"[CouncilRunner] 온톨로지 기반 페르소나 선택: {ontology_path}")
        personas = _select_personas_from_ontology(ontology_path, persona_count)
    else:
        personas = _select_personas_default(persona_count)

    print(f"[CouncilRunner] 선택된 페르소나 ({len(personas)}명):")
    for p in personas:
        print(f"  - {p['name']} ({p['role']})")

    # 메타데이터 저장
    meta = {
        "council_id": council_id,
        "topic": topic,
        "timestamp": timestamp,
        "personas": personas,
        "max_rounds": max_rounds,
        "convergence_threshold": convergence_threshold,
        "status": "round_1_prompts_generated",
    }
    meta_path = council_dir / "meta.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # Round 1 프롬프트 생성
    print(f"\n[CouncilRunner] Round 1 프롬프트 생성 중...")
    round1_prompt_files = _generate_round1_prompts(topic, personas, council_id, council_dir)

    # 오케스트레이션 가이드
    guide_path = _write_orchestration_guide(
        council_dir, council_id, topic, personas, round1_prompt_files, timestamp
    )

    print(f"\n[CouncilRunner] 생성 완료!")
    print(f"  Council 디렉토리: {council_dir}")
    print(f"  오케스트레이션 가이드: {guide_path}")
    print(f"\n  Round 1 프롬프트 파일들 ({len(round1_prompt_files)}개):")
    for pf in round1_prompt_files:
        print(f"    - {pf.name}")

    print(f"\n[CouncilRunner] 다음 단계:")
    print(f"  1. 위 프롬프트 파일들을 각 Agent에게 실행 (병렬)")
    print(f"  2. 결과 파일이 생성되면:")
    print(f"     python3 council-runner.py --resume {council_id} --topic \"{topic}\"")
    print(f"  3. 최종 리포트 생성:")
    print(f"     python3 council-runner.py --finalize {council_id}")

    # 결과 요약 출력
    summary = {
        "council_id": council_id,
        "topic": topic,
        "personas": [{"name": p["name"], "role": p["role"]} for p in personas],
        "round1_prompt_files": [str(pf) for pf in round1_prompt_files],
        "orchestration_guide": str(guide_path),
        "meta": str(meta_path),
    }
    print(f"\n[CouncilRunner] JSON 요약:")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _resume_council(
    council_id: str,
    topic: str,
    max_rounds: int,
    convergence_threshold: float,
    output_path: Path | None,
) -> None:
    """기존 Council을 재개하여 다음 라운드 프롬프트 생성."""
    council_dir = _COUNCIL_LOGS_DIR / council_id
    if not council_dir.exists():
        print(f"[CouncilRunner] 오류: Council 디렉토리를 찾을 수 없음: {council_dir}", file=sys.stderr)
        sys.exit(1)

    meta_path = council_dir / "meta.json"
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    personas = meta["personas"]
    topic = topic or meta["topic"]
    convergence_threshold = meta.get("convergence_threshold", convergence_threshold)
    max_rounds = max_rounds or meta.get("max_rounds", 5)

    # 완료된 라운드 확인
    completed_round = 0
    all_round_results: dict[int, list[dict[str, Any]]] = {}

    for round_num in range(1, max_rounds + 1):
        results = _collect_round_results(council_dir, round_num, personas)
        if results:
            all_round_results[round_num] = results
            completed_round = round_num
        else:
            break

    if completed_round == 0:
        print(f"[CouncilRunner] 아직 완료된 라운드가 없습니다. Round 1 결과를 먼저 수집하세요.")
        return

    print(f"[CouncilRunner] 완료된 라운드: {completed_round}")

    # 합의 측정
    last_results = all_round_results[completed_round]
    avg_confidence, consensus_desc = _measure_consensus(last_results)

    print(f"[CouncilRunner] 현재 합의 수준: confidence={avg_confidence:.3f} ({consensus_desc})")

    # 합의 달성 또는 최대 라운드 도달
    if avg_confidence >= convergence_threshold:
        print(f"[CouncilRunner] 합의 달성! (threshold: {convergence_threshold})")
        _finalize_council(council_id, output_path, all_round_results, personas, topic, completed_round)
        return

    if completed_round >= max_rounds:
        print(f"[CouncilRunner] 최대 라운드 도달 ({max_rounds}). 최종 리포트 생성.")
        _finalize_council(council_id, output_path, all_round_results, personas, topic, completed_round)
        return

    # 다음 라운드 프롬프트 생성
    next_round = completed_round + 1
    print(f"\n[CouncilRunner] Round {next_round} 프롬프트 생성 중...")

    prompt_files = _generate_roundN_prompts(
        topic, personas, council_id, council_dir,
        next_round, last_results
    )

    print(f"[CouncilRunner] Round {next_round} 프롬프트 파일들 ({len(prompt_files)}개):")
    for pf in prompt_files:
        print(f"  - {pf.name}")

    print(f"\n[CouncilRunner] 다음 단계:")
    print(f"  1. 위 프롬프트 파일들을 각 Agent에게 실행 (병렬)")
    print(f"  2. 결과 수집 후 재개:")
    print(f"     python3 council-runner.py --resume {council_id} --topic \"{topic}\"")


def _finalize_council(
    council_id: str,
    output_path: Path | None,
    all_round_results: dict[int, list[dict[str, Any]]] | None = None,
    personas: list[dict[str, Any]] | None = None,
    topic: str | None = None,
    total_rounds: int | None = None,
) -> None:
    """최종 Council Report 생성."""
    council_dir = _COUNCIL_LOGS_DIR / council_id
    if not council_dir.exists():
        print(f"[CouncilRunner] 오류: Council 디렉토리를 찾을 수 없음: {council_dir}", file=sys.stderr)
        sys.exit(1)

    # 메타데이터 로드
    meta_path = council_dir / "meta.json"
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    topic = topic or meta["topic"]
    personas = personas or meta["personas"]

    # 모든 라운드 결과 수집 (없으면 다시 수집)
    if all_round_results is None:
        all_round_results = {}
        for round_num in range(1, meta.get("max_rounds", 5) + 1):
            results = _collect_round_results(council_dir, round_num, personas)
            if results:
                all_round_results[round_num] = results
            else:
                break

    if not all_round_results:
        print(f"[CouncilRunner] 경고: 수집된 결과가 없습니다. 빈 리포트를 생성합니다.")

    total_rounds = total_rounds or max(all_round_results.keys(), default=0)
    timestamp = meta.get("timestamp", datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))

    report = _generate_council_report(
        topic, council_id, personas, all_round_results, total_rounds, timestamp
    )

    # 저장 경로 결정
    if output_path:
        report_path = output_path
    else:
        report_path = council_dir / "council-report.json"

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n[CouncilRunner] Council Report 생성 완료!")
    print(f"  경로: {report_path}")
    print(f"\n[CouncilRunner] 리포트 요약:")
    print(f"  주제: {report['topic']}")
    print(f"  합의: {report['consensus']}")
    print(f"  반론: {report['dissent']}")
    print(f"  confidence: {report['confidence']:.3f}")
    print(f"  라운드: {report['rounds']}")
    print(f"\n  JSON:")
    print(json.dumps(report, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="MuchaNipo CouncilRunner — 다중 페르소나 토론 자동화 오케스트레이터",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  # 신규 Council 시작
  python3 council-runner.py --topic "MIRIVA 앱의 시장 출시 전략"

  # 온톨로지 기반 페르소나 선택
  python3 council-runner.py --topic "주제" --ontology logs/ontology-xxx.json

  # 페르소나 수와 최대 라운드 지정
  python3 council-runner.py --topic "주제" --personas 5 --max-rounds 3

  # 특정 출력 파일 지정
  python3 council-runner.py --topic "주제" --output council-report.json

  # 기존 Council 재개 (Round N 프롬프트 생성)
  python3 council-runner.py --resume council-20260101T120000Z --topic "주제"

  # 최종 리포트 생성
  python3 council-runner.py --finalize council-20260101T120000Z
        """,
    )

    parser.add_argument(
        "--topic", "-t",
        type=str,
        help="토론 주제",
    )
    parser.add_argument(
        "--ontology", "-o",
        type=Path,
        default=None,
        help="온톨로지 JSON 파일 경로 (entity_types 기반 페르소나 선택)",
    )
    parser.add_argument(
        "--personas", "-p",
        type=int,
        default=5,
        help="페르소나 수 (기본: 5, 범위: 3-7)",
    )
    parser.add_argument(
        "--max-rounds", "-r",
        type=int,
        default=None,
        help="최대 토론 라운드 수 (기본: config.json 설정 또는 5)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="최종 리포트 출력 경로 (기본: council-logs/{council_id}/council-report.json)",
    )
    parser.add_argument(
        "--resume",
        type=str,
        default=None,
        metavar="COUNCIL_ID",
        help="기존 Council 재개 (council_id 지정)",
    )
    parser.add_argument(
        "--finalize",
        type=str,
        default=None,
        metavar="COUNCIL_ID",
        help="최종 리포트 생성 (council_id 지정)",
    )

    args = parser.parse_args()

    # 검증
    if not args.resume and not args.finalize and not args.topic:
        parser.error("--topic 또는 --resume / --finalize 중 하나는 필수입니다.")

    run_council(
        topic=args.topic or "",
        ontology_path=args.ontology,
        persona_count=args.personas,
        max_rounds=args.max_rounds,
        output_path=args.output,
        resume_council_id=args.resume,
        finalize_council_id=args.finalize,
    )


if __name__ == "__main__":
    main()
