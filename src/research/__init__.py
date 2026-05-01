"""AutoResearch planning and mock execution."""

from .planner import ResearchPlan, ResearchPlanner

__all__ = ["ResearchPlan", "ResearchPlanner", "MockResearchRunner"]


def __getattr__(name: str):
    if name == "MockResearchRunner":
        from .runner import MockResearchRunner

        return MockResearchRunner
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
