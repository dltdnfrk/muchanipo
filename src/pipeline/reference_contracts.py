"""Reference-project contracts for the six Muchanipo implementation stages."""
from __future__ import annotations

from dataclasses import dataclass

from .stages import Stage


@dataclass(frozen=True)
class StageReferenceContract:
    step: int
    name: str
    stages: tuple[Stage, ...]
    references: tuple[str, ...]
    notes: tuple[str, ...] = ()


CONTRACTS: tuple[StageReferenceContract, ...] = (
    StageReferenceContract(
        step=1,
        name="인터뷰 / 요구사항 정리",
        stages=(Stage.IDEA_DUMP, Stage.INTERVIEW),
        references=("GPTaku show-me-the-prd", "GStack office-hours"),
        notes=(
            "show-me-the-prd는 제품 요구사항 문서화와 후속 질문 생성을 담당한다.",
            "office-hours는 research framing과 숨은 전제 검토를 담당한다.",
        ),
    ),
    StageReferenceContract(
        step=2,
        name="목표 설정 / 연구 지도 작성",
        stages=(Stage.TARGETING,),
        references=("GStack plan-review", "학술 자료 검색 API", "GBrain 지식 구조", "Plannotator"),
    ),
    StageReferenceContract(
        step=3,
        name="자료 수집 / 자동 연구",
        stages=(Stage.RESEARCH,),
        references=("Karpathy Autoresearch", "InsightForge", "MemPalace", "학술 자료 검색 API"),
        notes=(
            "검색 질문, 근거 수집 기준, 재검색 조건을 명시해 두루뭉실한 자료 수집을 막는다.",
        ),
    ),
    StageReferenceContract(
        step=4,
        name="근거 검증 / 지식 정리",
        stages=(Stage.EVIDENCE,),
        references=("GBrain 현재 결론 + 사건 기록", "출처 기반 연구 원칙", "Plannotator"),
    ),
    StageReferenceContract(
        step=5,
        name="Council / 다중 관점 토론",
        stages=(Stage.COUNCIL,),
        references=("MiroFish", "OASIS / CAMEL-AI", "Nemotron-Personas-Korea", "HACHIMI", "MAP-Elites"),
    ),
    StageReferenceContract(
        step=6,
        name="보고서 작성 / 학습 축적",
        stages=(Stage.REPORT, Stage.VAULT, Stage.AGENTS, Stage.DONE),
        references=("ReACT 보고서 작성 패턴", "Karpathy LLM Wiki Pattern", "GBrain", "GStack retro", "GStack learnings_log"),
    ),
)


def contract_for_stage(stage: Stage) -> StageReferenceContract | None:
    for contract in CONTRACTS:
        if stage in contract.stages:
            return contract
    return None


def references_for_stage(stage: Stage) -> list[str]:
    contract = contract_for_stage(stage)
    return list(contract.references) if contract else []
