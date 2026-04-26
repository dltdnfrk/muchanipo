"""Stateful PRD-style interview session."""
from __future__ import annotations

from dataclasses import dataclass, field

from src.intake.idea_dump import IdeaDump

from .brief import ResearchBrief
from .rubric import coverage_score, missing_dimensions


@dataclass
class InterviewSession:
    raw_idea: str
    answers: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_idea(cls, idea: IdeaDump) -> "InterviewSession":
        idea.validate()
        return cls(raw_idea=idea.raw_text)

    def answer(self, dimension: str, text: str) -> None:
        self.answers[dimension] = text.strip()

    @property
    def coverage_score(self) -> float:
        return coverage_score(self.answers)

    @property
    def missing_dimensions(self) -> list[str]:
        return missing_dimensions(self.answers)

    def to_brief(self) -> ResearchBrief:
        question = self.answers.get("research_question") or self.raw_idea
        purpose = self.answers.get("purpose") or "clarify next decision"
        return ResearchBrief(
            raw_idea=self.raw_idea,
            research_question=question,
            purpose=purpose,
            context=self.answers.get("context", ""),
            deliverable_type=self.answers.get("deliverable_type", "report"),
            quality_bar=self.answers.get("quality_bar", "evidence-backed"),
            coverage_score=self.coverage_score,
        )
