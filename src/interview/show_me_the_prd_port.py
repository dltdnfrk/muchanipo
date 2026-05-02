"""Faithful local runtime contract for the vendored show-me-the-prd plugin.

The upstream project is a Claude/GPTaku prompt plugin, so the executable unit is
its workflow contract rather than a Python package.  This module keeps that
contract explicit and testable for Muchanipo Stage 1 instead of treating the
project as a vague inspiration source.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence


UPSTREAM_REPOSITORY = "https://github.com/fivetaku/show-me-the-prd"
UPSTREAM_MARKETPLACE = "https://github.com/fivetaku/gptaku_plugins"
UPSTREAM_COMMIT = "7b22b070a685115a8687ea95fb95d398e4daf043"
UPSTREAM_LICENSE = "MIT"
VENDORED_ROOT = Path("third_party/show-me-the-prd")
VENDORED_PATHS: tuple[str, ...] = (
    "third_party/show-me-the-prd/UPSTREAM.md",
    "third_party/show-me-the-prd/README.md",
    "third_party/show-me-the-prd/README.ko.md",
    "third_party/show-me-the-prd/CHANGELOG.md",
    "third_party/show-me-the-prd/.claude-plugin/plugin.json",
    "third_party/show-me-the-prd/commands/show-me-the-prd.md",
    "third_party/show-me-the-prd/skills/show-me-the-prd/SKILL.md",
    "third_party/show-me-the-prd/skills/show-me-the-prd/references/document-templates.md",
    "third_party/show-me-the-prd/skills/show-me-the-prd/references/interview-guide.md",
    "third_party/show-me-the-prd/skills/show-me-the-prd/references/research-strategy.md",
)


@dataclass(frozen=True)
class UpstreamSource:
    name: str
    repository: str
    marketplace_repository: str
    commit: str
    license: str
    vendored_paths: tuple[str, ...]


@dataclass(frozen=True)
class InterviewOption:
    label: str
    description: str
    recommended: bool = False
    complexity: str = ""


@dataclass(frozen=True)
class InterviewQuestion:
    turn: int
    header: str
    question: str
    multi_select: bool
    options: tuple[InterviewOption, ...]
    source_rule: str
    preview_required: bool = False


@dataclass(frozen=True)
class ResearchBatch:
    after_turn: int
    queries: tuple[str, ...]
    destination_turn: int


@dataclass(frozen=True)
class DocumentSpec:
    path: str
    purpose: str


@dataclass(frozen=True)
class ShowMeThePrdPlan:
    source: UpstreamSource
    idea: str
    detected_domain: str
    missing_initial_fields: tuple[str, ...]
    initial_questions: tuple[InterviewQuestion, ...]
    workflow_questions: tuple[InterviewQuestion, ...]
    research_batches: tuple[ResearchBatch, ...]
    documents: tuple[DocumentSpec, ...]
    evidence_markers: tuple[str, ...] = field(default_factory=tuple)

    @property
    def question_count(self) -> int:
        return len(self.initial_questions) + len(self.workflow_questions)

    @property
    def document_paths(self) -> tuple[str, ...]:
        return tuple(item.path for item in self.documents)


def upstream_source() -> UpstreamSource:
    return UpstreamSource(
        name="GPTaku show-me-the-prd",
        repository=UPSTREAM_REPOSITORY,
        marketplace_repository=UPSTREAM_MARKETPLACE,
        commit=UPSTREAM_COMMIT,
        license=UPSTREAM_LICENSE,
        vendored_paths=VENDORED_PATHS,
    )


def build_show_me_the_prd_plan(
    idea: str,
    *,
    answers: Mapping[str, str] | None = None,
) -> ShowMeThePrdPlan:
    """Build the Stage 1 runtime plan from the upstream workflow.

    Upstream Turn 1 asks only unclear items, then runs research before later
    turns.  The generated plan is intentionally data-only so server, CLI, and
    tests can prove which parts of the upstream workflow are active.
    """
    cleaned = _clean(idea)
    answers = answers or {}
    detected_domain = _detect_domain(cleaned)
    missing = _missing_initial_fields(cleaned, answers)
    initial = tuple(_initial_question(field, detected_domain) for field in missing[:3])
    if not initial:
        initial = (_initial_question("core_problem", detected_domain),)
    workflow_questions = (
        _feature_question(detected_domain),
        _mvp_question(detected_domain),
        _data_model_question(detected_domain),
        _phase_question(),
        _stack_question(detected_domain),
        _auth_question(),
    )
    research_batches = (
        ResearchBatch(
            after_turn=1,
            destination_turn=2,
            queries=(
                f"{detected_domain} app features 2026",
                f"{detected_domain} app complaints alternatives",
                f"{detected_domain} app essential features",
            ),
        ),
        ResearchBatch(
            after_turn=2,
            destination_turn=3,
            queries=(
                f"{detected_domain} implementation best practices",
                f"{detected_domain} data model design",
            ),
        ),
        ResearchBatch(
            after_turn=4,
            destination_turn=5,
            queries=(
                f"best tech stack for {detected_domain} app 2026",
                f"{detected_domain} app authentication best practices",
            ),
        ),
    )
    return ShowMeThePrdPlan(
        source=upstream_source(),
        idea=cleaned,
        detected_domain=detected_domain,
        missing_initial_fields=tuple(missing),
        initial_questions=initial,
        workflow_questions=workflow_questions,
        research_batches=research_batches,
        documents=_documents(),
        evidence_markers=(
            "dynamic_unclear_item_questions",
            "research_batch_before_feature_choice",
            "feature_and_mvp_choice",
            "data_model_confirmation",
            "phase_confirmation",
            "stack_and_auth_choice",
            "four_document_output",
        ),
    )


def show_me_the_prd_artifacts(
    plan: ShowMeThePrdPlan,
    *,
    user_answer_count: int,
    office_hours_fill_count: int,
) -> dict[str, str]:
    mode = (
        "user_interview"
        if office_hours_fill_count == 0 and user_answer_count > 0
        else "mixed_user_office_hours"
        if user_answer_count > 0
        else "synthetic_office_hours_fill"
    )
    return {
        "show_prd_source": plan.source.repository,
        "show_prd_marketplace_source": plan.source.marketplace_repository,
        "show_prd_source_commit": plan.source.commit,
        "show_prd_license": plan.source.license,
        "show_prd_vendored_path_count": str(len(plan.source.vendored_paths)),
        "show_prd_runtime_mode": mode,
        "show_prd_detected_domain": plan.detected_domain,
        "show_prd_missing_initial_fields": ",".join(plan.missing_initial_fields),
        "show_prd_initial_question_count": str(len(plan.initial_questions)),
        "show_prd_workflow_question_count": str(len(plan.workflow_questions)),
        "show_prd_research_batch_count": str(len(plan.research_batches)),
        "show_prd_research_queries": "|".join(
            query for batch in plan.research_batches for query in batch.queries
        ),
        "show_prd_document_outputs": ",".join(plan.document_paths),
        "show_prd_evidence_markers": ",".join(plan.evidence_markers),
    }


def render_show_me_the_prd_documents(
    plan: ShowMeThePrdPlan,
    *,
    answers: Mapping[str, str],
    planning: Mapping[str, Any],
) -> dict[str, str]:
    """Render the four upstream document outputs from live interview answers.

    The upstream plugin is prompt-native.  These markdown outputs are the
    executable product artifact for the in-app port: they prove that Stage 1
    collected answers, projected them into a PRD model, and produced the same
    four-document contract the vendored workflow advertises.
    """
    prd = _mapping(planning.get("planning_prd"))
    feature_hierarchy = _list(planning.get("feature_hierarchy"))
    user_flow = _mapping(planning.get("user_flow"))
    docs = {
        "PRD/01_PRD.md": _render_prd(plan, answers=answers, prd=prd),
        "PRD/02_DATA_MODEL.md": _render_data_model(plan, prd=prd, feature_hierarchy=feature_hierarchy),
        "PRD/03_PHASES.md": _render_phases(plan, answers=answers, feature_hierarchy=feature_hierarchy),
        "PRD/04_PROJECT_SPEC.md": _render_project_spec(plan, prd=prd, user_flow=user_flow),
    }
    return {path: docs[path] for path in plan.document_paths}


def show_me_the_prd_document_manifest(documents: Mapping[str, str]) -> list[dict[str, str | int]]:
    """Return a compact JSON-safe manifest for UI and event assertions."""
    manifest: list[dict[str, str | int]] = []
    for path, markdown in documents.items():
        first_heading = next(
            (line.lstrip("# ").strip() for line in str(markdown).splitlines() if line.startswith("#")),
            path,
        )
        manifest.append(
            {
                "path": path,
                "title": first_heading,
                "chars": len(str(markdown)),
                "preview": str(markdown).strip()[:600],
            }
        )
    return manifest


def vendored_paths_exist(repo_root: Path | str = ".") -> bool:
    root = Path(repo_root)
    return all((root / path).exists() for path in VENDORED_PATHS)


def _render_prd(
    plan: ShowMeThePrdPlan,
    *,
    answers: Mapping[str, str],
    prd: Mapping[str, Any],
) -> str:
    overview = _mapping(prd.get("overview"))
    core_value = _mapping(prd.get("core_value"))
    scenarios = _list(prd.get("target_scenarios"))
    metrics = _list(prd.get("success_metrics"))
    pending = _list(prd.get("pending_fields"))
    lines = [
        "# Product Requirements Document",
        "",
        f"- Source workflow: {plan.source.name}",
        f"- Upstream commit: `{plan.source.commit}`",
        f"- Detected domain: `{plan.detected_domain}`",
        "",
        "## Overview",
        "",
        f"- One-line: {_clean(str(overview.get('one_line') or plan.idea))}",
        f"- Goal: {_clean(str(overview.get('goal') or answers.get('purpose') or 'pending'))}",
        f"- Background: {_clean(str(overview.get('background') or answers.get('context') or 'pending'))}",
        "",
        "## Core Value",
        "",
        f"- Problem: {_clean(str(core_value.get('problem') or answers.get('research_question') or plan.idea))}",
        f"- Resolution: {_clean(str(core_value.get('resolution') or answers.get('purpose') or 'pending'))}",
        f"- Differentiator: {_clean(str(core_value.get('differentiator') or answers.get('known') or 'pending'))}",
        "",
        "## Target Scenarios",
        "",
    ]
    for scenario in scenarios:
        item = _mapping(scenario)
        lines.append(f"- **{_clean(str(item.get('user_group') or 'primary user'))}**: {_clean(str(item.get('scenario') or plan.idea))}")
    lines.extend(["", "## Success Metrics", ""])
    for metric in metrics:
        lines.append(f"- {_clean(str(metric))}")
    if pending:
        lines.extend(["", "## Pending Fields", ""])
        for item in pending:
            lines.append(f"- {item}")
    return "\n".join(lines).strip() + "\n"


def _render_data_model(
    plan: ShowMeThePrdPlan,
    *,
    prd: Mapping[str, Any],
    feature_hierarchy: list[Any],
) -> str:
    properties = _mapping(prd.get("properties"))
    roles = _list(properties.get("roles"))
    environments = _list(properties.get("environments"))
    features = _feature_lines(feature_hierarchy)
    lines = [
        "# Data Model",
        "",
        f"- Domain: `{plan.detected_domain}`",
        f"- Category: `{_clean(str(properties.get('category') or 'unspecified'))}`",
        "",
        "## Entities",
        "",
        "- `Idea`: original user request and interview context",
        "- `ResearchBrief`: PRD overview, purpose, context, constraints",
        "- `Feature`: user-visible capability selected during interview",
        "- `EvidencePolicy`: quality bar and source requirements",
        "- `ReviewDecision`: plan approval, inline annotations, and audit trail",
        "",
        "## Roles",
        "",
    ]
    for role in roles:
        lines.append(f"- {role}")
    lines.extend(["", "## Environments", ""])
    for env in environments:
        lines.append(f"- {env}")
    lines.extend(["", "## Feature Seeds", ""])
    lines.extend(features or ["- pending feature selection"])
    return "\n".join(lines).strip() + "\n"


def _render_phases(
    plan: ShowMeThePrdPlan,
    *,
    answers: Mapping[str, str],
    feature_hierarchy: list[Any],
) -> str:
    deliverable = _clean(answers.get("deliverable_type", "")) or "reviewed research output"
    quality = _clean(answers.get("quality_bar", "")) or "evidence-backed"
    feature_lines = _feature_lines(feature_hierarchy)
    lines = [
        "# Build Phases",
        "",
        "## Phase 1 - Minimum Real Workflow",
        "",
        f"- Ship the interview-to-PRD flow for `{plan.detected_domain}`.",
        f"- Produce: {deliverable}.",
        "- Require plan review before targeting.",
        "",
        "## Phase 2 - Evidence Depth",
        "",
        f"- Enforce quality bar: {quality}.",
        "- Connect academic and local-memory evidence before report writing.",
        "",
        "## Phase 3 - Automation and Governance",
        "",
        "- Add council review, report learning log, and reusable project memory.",
        "",
        "## Feature Carryover",
        "",
    ]
    lines.extend(feature_lines or ["- pending feature selection"])
    return "\n".join(lines).strip() + "\n"


def _render_project_spec(
    plan: ShowMeThePrdPlan,
    *,
    prd: Mapping[str, Any],
    user_flow: Mapping[str, Any],
) -> str:
    nodes = _list(user_flow.get("nodes"))
    edges = _list(user_flow.get("edges"))
    lines = [
        "# Project Specification",
        "",
        "## Runtime Rules",
        "",
        "- Do not market synthetic OfficeHours fill as completed user interview.",
        "- Preserve upstream source, commit, and license metadata in artifacts.",
        "- Keep plan edits reviewable before targeting and evidence collection.",
        "- Surface pending fields instead of inventing certainty.",
        "",
        "## Source Contract",
        "",
        f"- Repository: {plan.source.repository}",
        f"- Commit: `{plan.source.commit}`",
        f"- License declaration: {plan.source.license}",
        f"- Evidence markers: {', '.join(plan.evidence_markers)}",
        "",
        "## User Flow Nodes",
        "",
    ]
    for node in nodes:
        item = _mapping(node)
        lines.append(f"- `{item.get('id', '?')}`: {item.get('label', '')}")
    lines.extend(["", "## User Flow Edges", ""])
    for edge in edges:
        item = _mapping(edge)
        lines.append(f"- `{item.get('from', '?')}` -> `{item.get('to', '?')}`: {item.get('label', '')}")
    return "\n".join(lines).strip() + "\n"


def _feature_lines(feature_hierarchy: list[Any]) -> list[str]:
    lines: list[str] = []
    for requirement in feature_hierarchy:
        req = _mapping(requirement)
        req_name = _clean(str(req.get("name") or "requirement"))
        lines.append(f"- Requirement: {req_name}")
        for feature in _list(req.get("features")):
            feat = _mapping(feature)
            feat_name = _clean(str(feat.get("name") or "feature"))
            lines.append(f"  - Feature: {feat_name}")
            for spec in _list(feat.get("specifications")):
                spec_item = _mapping(spec)
                lines.append(
                    f"    - Specification: {_clean(str(spec_item.get('name') or 'spec'))} - "
                    f"{_clean(str(spec_item.get('description') or ''))}"
                )
    return lines


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _missing_initial_fields(idea: str, answers: Mapping[str, str]) -> list[str]:
    fields = {
        "core_problem": (
            "problem",
            "pain",
            "solve",
            "issue",
            "불편",
            "문제",
            "해결",
            "검증",
        ),
        "target_user": (
            "user",
            "customer",
            "team",
            "farmer",
            "농가",
            "사용자",
            "고객",
            "팀",
        ),
        "platform": ("web", "mobile", "ios", "android", "웹", "앱", "모바일"),
        "scale_constraint": (
            "budget",
            "deadline",
            "mvp",
            "enterprise",
            "예산",
            "기한",
            "첫",
            "규모",
        ),
    }
    lowered = idea.lower()
    missing: list[str] = []
    for field, keywords in fields.items():
        if answers.get(field):
            continue
        if not any(keyword.lower() in lowered for keyword in keywords):
            missing.append(field)
    return missing


def _initial_question(field: str, domain: str) -> InterviewQuestion:
    question_map = {
        "core_problem": (
            "Idea",
            "What problem should this product or research plan solve first?",
            (
                InterviewOption(
                    "Clarify the pain first (recommended)",
                    "Start from the user's current friction; strong PRDs need the problem before features.",
                    recommended=True,
                    complexity="Simple",
                ),
                InterviewOption(
                    "Validate a market decision",
                    "Frame the output around go/no-go evidence; useful when business risk is the main issue.",
                    complexity="Moderate",
                ),
                InterviewOption(
                    "Design an implementation plan",
                    "Focus on building steps; useful only when the problem and users are already clear.",
                    complexity="Moderate",
                ),
            ),
        ),
        "target_user": (
            "Users",
            f"Who will use the {domain} product or decision output?",
            (
                InterviewOption(
                    "A narrow primary user (recommended)",
                    "Keeps MVP scope small and testable; may defer secondary audiences.",
                    recommended=True,
                    complexity="Simple",
                ),
                InterviewOption(
                    "Several stakeholder groups",
                    "Captures buyer/user/admin differences; takes more interview and council work.",
                    complexity="Moderate",
                ),
                InterviewOption(
                    "Public or broad market",
                    "Useful for consumer products; makes evidence and segmentation harder.",
                    complexity="Complex",
                ),
            ),
        ),
        "platform": (
            "Platform",
            "Where should the first version run?",
            (
                InterviewOption(
                    "Web app first (recommended)",
                    "Fast to ship and easy to share; weaker for native device features.",
                    recommended=True,
                    complexity="Simple",
                ),
                InterviewOption(
                    "Mobile app first",
                    "Better for field or camera workflows; store release and device testing add complexity.",
                    complexity="Complex",
                ),
                InterviewOption(
                    "Both web and mobile",
                    "Covers more users; first version takes longer and needs stricter phase planning.",
                    complexity="Complex",
                ),
            ),
        ),
        "scale_constraint": (
            "Constraints",
            "What first-version constraint should shape the PRD?",
            (
                InterviewOption(
                    "Small MVP in phases (recommended)",
                    "Keeps the first release real and shippable; advanced features wait.",
                    recommended=True,
                    complexity="Simple",
                ),
                InterviewOption(
                    "Production-ready from day one",
                    "Fits regulated or paid products; requires more design and testing.",
                    complexity="Complex",
                ),
                InterviewOption(
                    "Research-only prototype",
                    "Good for discovery; must not be marketed as a finished app.",
                    complexity="Simple",
                ),
            ),
        ),
    }
    header, question, options = question_map.get(field, question_map["core_problem"])
    return InterviewQuestion(
        turn=1,
        header=header,
        question=question,
        multi_select=False,
        options=options,
        source_rule="Ask only unclear items from the idea gap analysis.",
    )


def _feature_question(domain: str) -> InterviewQuestion:
    return InterviewQuestion(
        turn=2,
        header="Core features",
        question="Which researched features are essential for the first version?",
        multi_select=True,
        options=(
            InterviewOption(
                f"{domain.title()} intake and profile (recommended)",
                "Simple - captures the minimum user/context data needed for a real workflow.",
                recommended=True,
                complexity="Simple",
            ),
            InterviewOption(
                "Evidence-backed recommendations",
                "Moderate - adds search and citation grounding; stronger outputs but more provider risk.",
                complexity="Moderate",
            ),
            InterviewOption(
                "Collaboration and approvals",
                "Moderate - useful for teams; requires roles, notifications, and audit trail.",
                complexity="Moderate",
            ),
            InterviewOption(
                "Automation and integrations",
                "Complex - powerful later, but external APIs and failures complicate the MVP.",
                complexity="Complex",
            ),
        ),
        source_rule="Populate options from live research before asking.",
    )


def _mvp_question(domain: str) -> InterviewQuestion:
    return InterviewQuestion(
        turn=2,
        header="MVP",
        question="Which first-version feature bundle should the PRD target?",
        multi_select=False,
        options=(
            InterviewOption(
                "Minimum real workflow (recommended)",
                f"Includes {domain} intake, one core result, and review. Fastest path to a usable product.",
                recommended=True,
                complexity="Simple",
            ),
            InterviewOption(
                "Evidence-rich workflow",
                "Adds research and citation depth. Better output quality with higher runtime cost.",
                complexity="Moderate",
            ),
            InterviewOption(
                "Full product loop",
                "Adds collaboration, automation, and integrations. Strong vision, slow first release.",
                complexity="Complex",
            ),
        ),
        source_rule="Offer MVP bundles after feature research.",
    )


def _data_model_question(domain: str) -> InterviewQuestion:
    return InterviewQuestion(
        turn=3,
        header="Data",
        question="Does this data model fit the selected workflow?",
        multi_select=False,
        preview_required=True,
        options=(
            InterviewOption(
                "Looks right (recommended)",
                "Use the proposed entities and relationships; simplest path to implementation.",
                recommended=True,
                complexity="Simple",
            ),
            InterviewOption(
                "Needs one change",
                "Keep the model but revise a key entity, relationship, or field.",
                complexity="Moderate",
            ),
            InterviewOption(
                f"I am unsure about the {domain} model",
                "Let the system keep the recommended structure and mark assumptions for review.",
                complexity="Simple",
            ),
        ),
        source_rule="Derive entities from selected features before confirmation.",
    )


def _phase_question() -> InterviewQuestion:
    return InterviewQuestion(
        turn=4,
        header="Phases",
        question="Is this phase split acceptable?",
        multi_select=False,
        preview_required=True,
        options=(
            InterviewOption(
                "Use this sequence (recommended)",
                "Phase 1 ships the MVP, Phase 2 expands, Phase 3 automates.",
                recommended=True,
                complexity="Simple",
            ),
            InterviewOption(
                "Change the order",
                "Reprioritize a feature before code starts.",
                complexity="Moderate",
            ),
            InterviewOption(
                "Split or merge phases",
                "Useful when release boundaries are too large or too small.",
                complexity="Moderate",
            ),
        ),
        source_rule="Split phases from complexity and dependencies.",
    )


def _stack_question(domain: str) -> InterviewQuestion:
    return InterviewQuestion(
        turn=5,
        header="Stack",
        question="Which researched technology stack should the build plan assume?",
        multi_select=False,
        preview_required=True,
        options=(
            InterviewOption(
                "Mainstream managed stack (recommended)",
                f"Good default for a {domain} app; simpler deployment and stronger AI-coding support.",
                recommended=True,
                complexity="Simple",
            ),
            InterviewOption(
                "Lower-cost self-hosted stack",
                "More control and lower service bills; more operations work.",
                complexity="Moderate",
            ),
            InterviewOption(
                "Enterprise/regulated stack",
                "Fits compliance-heavy products; slowest and most expensive first version.",
                complexity="Complex",
            ),
        ),
        source_rule="Fill comparison table from current docs/search before asking.",
    )


def _auth_question() -> InterviewQuestion:
    return InterviewQuestion(
        turn=5,
        header="Login",
        question="How should users log in?",
        multi_select=False,
        options=(
            InterviewOption(
                "Social login (recommended)",
                "Fast for users; depends on providers such as Google or Kakao.",
                recommended=True,
                complexity="Simple",
            ),
            InterviewOption(
                "Email and password",
                "Familiar and independent; password reset and security work are required.",
                complexity="Moderate",
            ),
            InterviewOption(
                "Magic link",
                "No password to remember; email delivery must be reliable.",
                complexity="Moderate",
            ),
            InterviewOption(
                "No login for MVP",
                "Fastest demo path; not suitable for personal or team data.",
                complexity="Simple",
            ),
        ),
        source_rule="Ask after stack research.",
    )


def _documents() -> tuple[DocumentSpec, ...]:
    return (
        DocumentSpec("PRD/01_PRD.md", "Product goals, users, stories, and non-goals."),
        DocumentSpec("PRD/02_DATA_MODEL.md", "Core entities and relationships."),
        DocumentSpec("PRD/03_PHASES.md", "Phase-by-phase build plan with start prompts."),
        DocumentSpec("PRD/04_PROJECT_SPEC.md", "AI behavior rules and never-do-this list."),
    )


def _detect_domain(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("farm", "agtech", "agri", "농", "작물")):
        return "agtech"
    if any(token in lowered for token in ("research", "논문", "리서치", "시장성")):
        return "research"
    if any(token in lowered for token in ("commerce", "shop", "store", "커머스", "판매")):
        return "commerce"
    if any(token in lowered for token in ("social", "community", "커뮤니티", "소셜")):
        return "community"
    words = re.findall(r"[A-Za-z0-9가-힣]+", lowered)
    return words[0] if words else "general"


def _clean(value: str) -> str:
    return " ".join(str(value or "").strip().split())
