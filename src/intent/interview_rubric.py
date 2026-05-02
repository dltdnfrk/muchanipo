#!/usr/bin/env python3
"""Interview Rubric (Phase 0b v2) — entropy-greedy 동적 재배치 + coverage gate.

C22-A: arXiv 2510.27410 (Nous "Dialogue as Discovery") greedy entropy + Anthropic
Interviewer rubric coverage 패턴 + 2601.14798 Teacher-Educator 5축 quality.

핵심:
- 6개 차원(Q1~Q6) 각각 RubricItem으로 추적
- next_uncovered() — entropy_estimate 최대(=가장 불확실) 차원 우선 선택
- coverage_rate ≥ 0.75 시 조기 종료 가능 (rubric_coverage_gate)
- LLM 호출 없음, stdlib only

이 모듈은 office_hours / plan_review / interview_prompts 모두에서 import.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class CoverageStatus(str, Enum):
    NOT_ASKED = "not_asked"
    ASKED_INSUFFICIENT = "asked_insufficient"
    COVERED = "covered"


@dataclass
class RubricItem:
    """6 PRD 차원 각각의 rubric 항목."""

    dimension_id: str          # "Q1_research_question" .. "Q6_quality"
    label: str                 # "research_question" / "purpose" / ...
    research_question: str     # 이 차원이 답하려는 메타 질문
    probe_hints: List[str] = field(default_factory=list)
    coverage_status: CoverageStatus = CoverageStatus.NOT_ASKED
    collected_answer: Optional[str] = None
    quality_score: float = 0.0     # 0.0~1.0, Teacher-Educator 5축 평균 프록시
    entropy_estimate: float = 1.0  # 1.0=완전 불확실, 0.0=확실

    def mark_answered(self, answer: str, quality: float) -> None:
        """답변 수집 + quality 평가 → entropy/status 업데이트."""
        self.collected_answer = answer
        self.quality_score = max(0.0, min(1.0, quality))
        self.entropy_estimate = 1.0 - self.quality_score
        if self.quality_score >= 0.7:
            self.coverage_status = CoverageStatus.COVERED
        elif self.quality_score > 0.0:
            self.coverage_status = CoverageStatus.ASKED_INSUFFICIENT
        else:
            self.coverage_status = CoverageStatus.NOT_ASKED


# ---------------------------------------------------------------------------
# Default 6 PRD items (interview_prompts.forcing_questions_korean과 동기화)
# ---------------------------------------------------------------------------
def _default_items() -> List[RubricItem]:
    return [
        RubricItem(
            dimension_id="Q1_research_question",
            label="research_question",
            research_question="PRD 개요: 무엇을 만들거나 검증하려는 아이디어인가?",
            probe_hints=[
                "한 문장 제품 정의",
                "원 토픽보다 한 단계 좁힌 질문",
                "측정 가능한 결과 형태",
                "목표 시점/범위",
            ],
        ),
        RubricItem(
            dimension_id="Q2_purpose",
            label="purpose",
            research_question="핵심 가치: 어떤 문제를 어떻게 해결하고 무엇을 결정하는가?",
            probe_hints=["사용자 문제", "해결 방식", "차별점", "의사결정용"],
        ),
        RubricItem(
            dimension_id="Q3_context",
            label="context",
            research_question="타겟 및 시나리오: 누가 어떤 상황에서 사용하는가?",
            probe_hints=["핵심 사용자", "사용 시나리오", "국가/지역", "산업 도메인"],
        ),
        RubricItem(
            dimension_id="Q4_known",
            label="known",
            research_question="배경·제약: 이미 알고 있거나 피해야 할 것은?",
            probe_hints=["이미 시도한 접근", "보유 데이터", "결정 완료 사항", "법무·예산·일정 제약"],
        ),
        RubricItem(
            dimension_id="Q5_deliverable",
            label="deliverable",
            research_question="기능명세 seed: 요구사항, 기능, 상세기능은 무엇인가?",
            probe_hints=[
                "요구사항",
                "기능",
                "상세 기능",
                "1페이지 요약",
                "리서치 리포트",
                "Slide deck",
                "Obsidian vault 누적",
            ],
        ),
        RubricItem(
            dimension_id="Q6_quality",
            label="quality",
            research_question="성공 지표와 검증 기준은? (Source A-D)",
            probe_hints=[
                "KPI",
                "리스크",
                "A: peer-review/공식 통계만",
                "B: 학술+산업 리포트",
                "C: 블로그/뉴스 포함",
                "D: 추정/논리 위주",
            ],
        ),
    ]


@dataclass
class InterviewRubric:
    """세션당 1개 — 6 차원 coverage 추적 + entropy-greedy 라우팅."""

    topic: str
    items: List[RubricItem] = field(default_factory=_default_items)

    # ------------------------------------------------------------------ Reads
    def coverage_rate(self) -> float:
        if not self.items:
            return 0.0
        covered = sum(
            1 for i in self.items if i.coverage_status == CoverageStatus.COVERED
        )
        return covered / len(self.items)

    def next_uncovered(self) -> Optional[RubricItem]:
        """arXiv 2510.27410 greedy: 미답변 차원 중 entropy 최대 선택.

        동률이면 정의 순서(Q1→Q6) 우선 — 안정성.
        """
        uncovered = [
            i for i in self.items if i.coverage_status != CoverageStatus.COVERED
        ]
        if not uncovered:
            return None
        return max(uncovered, key=lambda x: (x.entropy_estimate,
                                              -self.items.index(x)))

    def is_complete(self, threshold: float = 0.75) -> bool:
        return self.coverage_rate() >= threshold

    def uncovered_dimension_ids(self) -> List[str]:
        return [
            i.dimension_id
            for i in self.items
            if i.coverage_status != CoverageStatus.COVERED
        ]

    # ------------------------------------------------------------------ Writes
    def update(self, dimension_id: str, answer: str, quality: float) -> RubricItem:
        for item in self.items:
            if item.dimension_id == dimension_id:
                item.mark_answered(answer, quality)
                return item
        raise KeyError(f"Unknown dimension: {dimension_id}")

    def get(self, dimension_id: str) -> RubricItem:
        for item in self.items:
            if item.dimension_id == dimension_id:
                return item
        raise KeyError(f"Unknown dimension: {dimension_id}")
