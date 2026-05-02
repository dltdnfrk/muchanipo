"""Raw user idea capture for the first stage of muchanipo.

C32 wire: IdeaDump → ResearchBrief helper that runs the user input through
the existing OfficeHours.reframe() pipeline so council entry has a
DesignDoc-grounded brief instead of a single line of text.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover
    from src.interview.brief import ResearchBrief
    from src.intent.office_hours import DesignDoc


@dataclass
class IdeaDump:
    raw_text: str
    source: str = "user"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    attachments: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if not self.raw_text.strip():
            raise ValueError("IdeaDump.raw_text must not be empty")

    # ------------------------------------------------------------------
    # C32 real wire: OfficeHours.reframe() integration
    # ------------------------------------------------------------------
    def reframe(self, *, redact_pii: bool = True) -> "DesignDoc":
        """Run the raw idea through the gstack-style office hours reframe.

        Used to seed a DesignDoc-grounded ResearchBrief for the council
        entry rather than a single line of raw user text.
        """
        self.validate()
        from src.intent.office_hours import OfficeHours

        return OfficeHours().reframe(self.raw_text, redact_pii=redact_pii)

    def to_research_brief(
        self,
        *,
        purpose: Optional[str] = None,
        deliverable_type: str = "report",
        quality_bar: str = "evidence-backed",
        coverage_score: float = 0.5,
    ) -> "ResearchBrief":
        """End-to-end IdeaDump → ResearchBrief conversion.

        Uses OfficeHours.reframe to seed research_question / context /
        constraints from the surfaced design doc instead of leaving them
        empty as the C31 mock did.
        """
        from src.interview.brief import ResearchBrief
        from src.interview.product_planning import build_product_planning_projection

        design = self.reframe()
        question = design.pain_root or self.raw_text
        context = design.contrary_framing
        known_facts = list(design.implicit_capabilities)
        constraints = list(design.challenged_premises)
        answers = {
            "research_question": question,
            "purpose": purpose or "clarify next decision",
            "context": context,
            "known": "; ".join(known_facts),
            "deliverable_type": deliverable_type,
            "quality_bar": quality_bar,
        }
        planning = build_product_planning_projection(
            self.raw_text,
            answers,
            design_doc=design,
        )
        return ResearchBrief(
            raw_idea=self.raw_text,
            research_question=question,
            purpose=purpose or "clarify next decision",
            context=context,
            known_facts=known_facts,
            deliverable_type=deliverable_type,
            quality_bar=quality_bar,
            constraints=constraints,
            success_criteria=planning["planning_prd"].get("success_metrics", []),
            coverage_score=coverage_score,
            planning_prd=planning["planning_prd"],
            feature_hierarchy=planning["feature_hierarchy"],
            user_flow=planning["user_flow"],
            planning_review_policy=planning["planning_review_policy"],
        )
