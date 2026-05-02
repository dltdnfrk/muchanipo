"""Stateful PRD-style interview session.

C32 wire: routes question selection through src.intent.interview_prompts
(assess + select_next_question + build_question_options) so the C31 mock
session shares the entropy-greedy rubric and AskUserQuestion option builder
used by the rest of the stack.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.intake.idea_dump import IdeaDump
from src.intent.interview_prompts import (
    InterviewPlan,
    assess,
    build_question_options,
    quick_clarification_questions,
    select_next_question,
)
from src.intent.interview_rubric import InterviewRubric, RubricItem
from src.interview.product_planning import (
    build_product_planning_projection,
    split_planning_items,
)

from .brief import ResearchBrief
from .rubric import (
    _LABEL_TO_DIM_ID,
    coverage_score,
    missing_dimensions,
    rubric_from_answers,
)


@dataclass
class InterviewSession:
    raw_idea: str
    answers: Dict[str, str] = field(default_factory=dict)
    plan: Optional[InterviewPlan] = None
    rubric: Optional[InterviewRubric] = None

    @classmethod
    def from_idea(cls, idea: IdeaDump) -> "InterviewSession":
        idea.validate()
        plan = assess(idea.raw_text)
        rubric = InterviewRubric(topic=idea.raw_text[:80])
        return cls(raw_idea=idea.raw_text, plan=plan, rubric=rubric)

    def answer(self, dimension: str, text: str) -> None:
        cleaned = text.strip()
        self.answers[dimension] = cleaned
        if self.rubric is not None and cleaned:
            dim_id = _LABEL_TO_DIM_ID.get(dimension)
            if dim_id is not None:
                try:
                    self.rubric.update(dim_id, cleaned, quality=0.8)
                except KeyError:
                    pass

    @property
    def coverage_score(self) -> float:
        return coverage_score(self.answers)

    @property
    def missing_dimensions(self) -> List[str]:
        return missing_dimensions(self.answers)

    # ------------------------------------------------------------------
    # C32 entropy-greedy routing helpers
    # ------------------------------------------------------------------
    def next_question(self) -> Optional[RubricItem]:
        """Pick the next dimension to ask via interview_prompts.select_next_question."""
        if self.rubric is None:
            self.rubric = rubric_from_answers(self.raw_idea[:80], self.answers)
        return select_next_question(self.rubric)

    def question_options(self, dim_id: str) -> List[Dict[str, str]]:
        """AskUserQuestion-friendly options for a given rubric dimension."""
        return build_question_options(dim_id, topic=self.raw_idea, prev_answers=self.answers)

    def clarifications_for_quick_mode(self) -> List[Dict[str, str]]:
        """Mirror Phase 0a triage: when assess() said 'quick' return the
        short clarification prompts for the still-missing dimensions."""
        plan = self.plan or assess(self.raw_idea)
        return quick_clarification_questions(plan.missing_dimensions)

    # ------------------------------------------------------------------
    def to_brief(self) -> ResearchBrief:
        question = self.answers.get("research_question") or self.raw_idea
        purpose = self.answers.get("purpose") or "clarify next decision"
        planning = build_product_planning_projection(self.raw_idea, self.answers)
        return ResearchBrief(
            raw_idea=self.raw_idea,
            research_question=question,
            purpose=purpose,
            context=self.answers.get("context", ""),
            known_facts=_split_answer_list(self.answers.get("known", "")),
            deliverable_type=self.answers.get("deliverable_type", "report"),
            quality_bar=self.answers.get("quality_bar", "evidence-backed"),
            success_criteria=planning["planning_prd"].get("success_metrics", []),
            coverage_score=self.coverage_score,
            planning_prd=planning["planning_prd"],
            feature_hierarchy=planning["feature_hierarchy"],
            user_flow=planning["user_flow"],
            planning_review_policy=planning["planning_review_policy"],
        )


def _split_answer_list(value: str) -> list[str]:
    return split_planning_items(value)
