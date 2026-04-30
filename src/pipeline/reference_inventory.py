"""Reference implementation inventory for the six-stage Muchanipo runtime."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .reference_contracts import CONTRACTS


CATEGORY_CONCEPT_ONLY = "concept only"
CATEGORY_CLEAN_ROOM = "clean-room implementation"
CATEGORY_PARTIAL_PORT = "partial port"
CATEGORY_VENDORED = "vendored code"
CATEGORY_EXTERNAL = "external runtime/API"
CATEGORY_DATASET = "dataset"
GBRAIN_LICENSE_WARNING = (
    "GBrain license evidence is inconsistent across local docs and pinned checks; "
    "verify the exact revision before copying additional material."
)

VALID_CATEGORIES = (
    CATEGORY_CONCEPT_ONLY,
    CATEGORY_CLEAN_ROOM,
    CATEGORY_PARTIAL_PORT,
    CATEGORY_VENDORED,
    CATEGORY_EXTERNAL,
    CATEGORY_DATASET,
)


@dataclass(frozen=True)
class ReferenceInventoryItem:
    name: str
    category: str
    license: str
    stages: tuple[int, ...]
    aliases: tuple[str, ...] = ()
    code_paths: tuple[str, ...] = ()
    test_paths: tuple[str, ...] = ()
    implementation_notes: str = ""
    gap: str = ""
    license_warning: str = ""
    source_url: str = ""

    def as_dict(self, *, repo_root: Path | None = None) -> dict[str, Any]:
        return {
            "name": self.name,
            "aliases": list(self.aliases),
            "category": self.category,
            "license": self.license,
            "stages": list(self.stages),
            "code_paths": list(self.code_paths),
            "test_paths": list(self.test_paths),
            "implemented": bool(self.code_paths) and self.category != CATEGORY_CONCEPT_ONLY,
            "present_paths": _existing_paths(self.code_paths, repo_root=repo_root),
            "implementation_notes": self.implementation_notes,
            "gap": self.gap,
            "license_warning": self.license_warning,
            "source_url": self.source_url,
        }


REFERENCE_INVENTORY: tuple[ReferenceInventoryItem, ...] = (
    ReferenceInventoryItem(
        name="GPTaku show-me-the-prd",
        category=CATEGORY_CLEAN_ROOM,
        license="MIT",
        stages=(1,),
        aliases=("GPTaku show-me-the-prd",),
        code_paths=("src/intent/interview_prompts.py", "src/interview/session.py", "src/interview/brief.py"),
        test_paths=("tests/test_interview_prompts.py", "tests/test_interview_rubric.py", "tests/test_pipeline_reference_artifacts.py"),
        implementation_notes="Local interview prompts and ResearchBrief flow implement the PRD-style intake behavior; the GPTaku plugin itself is not vendored.",
        gap="No runtime module imports GPTaku or the marketplace plugin directly.",
        source_url="https://github.com/fivetaku/gptaku_plugins",
    ),
    ReferenceInventoryItem(
        name="GStack office-hours",
        category=CATEGORY_CLEAN_ROOM,
        license="unknown",
        stages=(1,),
        code_paths=("src/intent/office_hours.py",),
        test_paths=("tests/intent/test_office_hours.py", "tests/test_office_hours.py"),
        implementation_notes="Local office-hours analysis separates hidden assumptions and research framing from PRD intake.",
        source_url="https://github.com/garrytan/gstack",
    ),
    ReferenceInventoryItem(
        name="GStack plan-review",
        category=CATEGORY_CLEAN_ROOM,
        license="unknown",
        stages=(2,),
        code_paths=("src/intent/plan_review.py", "src/targeting/builder.py"),
        test_paths=("tests/test_plan_review.py", "tests/targeting/test_builder.py", "tests/test_pipeline_reference_artifacts.py"),
        implementation_notes="Consensus plan review and targeting-map construction are local implementations.",
        source_url="https://github.com/garrytan/gstack",
    ),
    ReferenceInventoryItem(
        name="학술 자료 검색 API",
        category=CATEGORY_EXTERNAL,
        license="service/API terms vary",
        stages=(2, 3),
        aliases=("OpenAlex", "Crossref", "Semantic Scholar", "Unpaywall", "arXiv", "CORE"),
        code_paths=(
            "src/research/academic/openalex.py",
            "src/research/academic/crossref.py",
            "src/research/academic/semantic_scholar.py",
            "src/research/academic/unpaywall.py",
            "src/research/academic/arxiv.py",
            "src/research/academic/core.py",
        ),
        test_paths=("tests/research/academic", "tests/test_research_real_wire.py"),
        implementation_notes="Local adapters query or normalize academic sources; OpenAlex targeting helpers provide institutions, journals, and seed-paper lookups.",
        source_url="https://openalex.org",
    ),
    ReferenceInventoryItem(
        name="GBrain 지식 구조",
        category=CATEGORY_PARTIAL_PORT,
        license="documented Apache-2.0; verify pinned revision before copying more",
        stages=(2,),
        aliases=("GBrain",),
        code_paths=("src/hitl/vault-router.py", "src/wiki/dream_cycle.py", "src/pipeline/reference_runtime.py"),
        test_paths=("tests/test_dream_cycle.py", "tests/test_muchanipo_terminal.py", "tests/test_pipeline_reference_artifacts.py"),
        implementation_notes="Local vault routing, compiled-truth, timeline, and wiki-style persistence mirror GBrain patterns.",
        license_warning=GBRAIN_LICENSE_WARNING,
        source_url="https://github.com/garrytan/gbrain",
    ),
    ReferenceInventoryItem(
        name="Plannotator",
        category=CATEGORY_EXTERNAL,
        license="external project/service",
        stages=(2, 4),
        code_paths=("src/hitl/plannotator_adapter.py", "src/hitl/plannotator_http.py"),
        test_paths=("tests/test_plannotator_adapter.py", "tests/test_plannotator_http.py", "tests/test_pipeline_reference_artifacts.py"),
        implementation_notes="Auto-approve, markdown, and HTTP HITL gates are local adapters around the Plannotator review concept.",
    ),
    ReferenceInventoryItem(
        name="Karpathy Autoresearch",
        category=CATEGORY_CLEAN_ROOM,
        license="MIT",
        stages=(3,),
        code_paths=("src/research/planner.py", "src/runtime/iteration_hooks.py", "src/eval/evolve_runner.py"),
        test_paths=("tests/test_iteration_hooks.py", "tests/test_evolve_runner.py", "tests/test_pipeline_reference_artifacts.py"),
        implementation_notes="Local research plans, stop conditions, and improvement hooks implement the iterative research loop.",
        source_url="https://github.com/karpathy/autoresearch",
    ),
    ReferenceInventoryItem(
        name="InsightForge",
        category=CATEGORY_PARTIAL_PORT,
        license="MiroFish-derived pattern; verify before copying more",
        stages=(3,),
        code_paths=("src/search/insight-forge.py", "src/research/queries.py"),
        test_paths=("tests/test_insight_forge_dedup.py", "tests/test_c31_research_evidence.py"),
        implementation_notes="Local query decomposition, deduplication, and search-result shaping are implemented in runnable code.",
        source_url="https://github.com/666ghj/MiroFish",
    ),
    ReferenceInventoryItem(
        name="MemPalace",
        category=CATEGORY_PARTIAL_PORT,
        license="unknown",
        stages=(3,),
        code_paths=("src/research/runner.py", "src/search/insight-forge.py"),
        test_paths=("tests/test_research_real_wire.py", "tests/test_pipeline_reference_artifacts.py"),
        implementation_notes="WebResearchRunner uses local vault search from InsightForge as a memory-first adapter/fallback.",
        gap="No MemPalace package or native storage engine is vendored; this is a local vault-search adapter.",
        source_url="https://github.com/mempalace",
    ),
    ReferenceInventoryItem(
        name="GBrain 현재 결론 + 사건 기록",
        category=CATEGORY_PARTIAL_PORT,
        license="documented Apache-2.0; verify pinned revision before copying more",
        stages=(4,),
        aliases=("현재 결론 + 사건 기록",),
        code_paths=("src/hitl/vault-router.py", "src/pipeline/reference_runtime.py", "src/wiki/dream_cycle.py"),
        test_paths=("tests/test_pipeline_reference_artifacts.py", "tests/test_dream_cycle.py"),
        implementation_notes="Compiled-truth and timeline artifacts are built from local report/evidence state.",
        license_warning=GBRAIN_LICENSE_WARNING,
        source_url="https://github.com/garrytan/gbrain",
    ),
    ReferenceInventoryItem(
        name="출처 기반 연구 원칙",
        category=CATEGORY_CLEAN_ROOM,
        license="project policy",
        stages=(4,),
        code_paths=("src/evidence/store.py", "src/evidence/provenance.py", "src/eval/citation_grounder.py"),
        test_paths=("tests/test_research_real_wire.py", "tests/test_citation_grounder.py", "tests/test_live_product_gate.py"),
        implementation_notes="Evidence references, provenance checks, and live-mode gates are enforced by local tests.",
    ),
    ReferenceInventoryItem(
        name="MiroFish",
        category=CATEGORY_PARTIAL_PORT,
        license="AGPL-3.0",
        stages=(5,),
        aliases=("MiroFish Crowd Intelligence",),
        code_paths=("src/agents/mirofish.py", "src/council/council-runner.py", "src/search/insight-forge.py", "src/search/react-report.py"),
        test_paths=("tests/test_council_real_wire.py", "tests/test_council_session_llm.py", "tests/test_pipeline_reference_artifacts.py"),
        implementation_notes="Local code implements selected crowd-simulation/search/report patterns; full upstream is not vendored.",
        gap="Keep AGPL-derived code isolated or clean-room before expanding beyond selected local ports.",
        license_warning="MiroFish is AGPL-3.0; do not classify as vendored code without a dedicated compliance review.",
        source_url="https://github.com/666ghj/MiroFish",
    ),
    ReferenceInventoryItem(
        name="OASIS / CAMEL-AI",
        category=CATEGORY_CLEAN_ROOM,
        license="Apache-2.0 or project-specific; verify upstream component before copying code",
        stages=(5,),
        aliases=("OASIS", "CAMEL-AI"),
        code_paths=("src/council/session.py", "src/council/prompts.py", "src/council/round_layers.py"),
        test_paths=("tests/test_council_session_llm.py", "tests/test_council_real_wire.py", "tests/test_pipeline_reference_artifacts.py"),
        implementation_notes="Council protocol is represented as local persona/session prompts and telemetry, not a vendored OASIS runtime.",
        gap="No CAMEL-AI/OASIS runtime module is imported for stage execution.",
        source_url="https://github.com/camel-ai/oasis",
    ),
    ReferenceInventoryItem(
        name="Nemotron-Personas-Korea",
        category=CATEGORY_DATASET,
        license="CC-BY-4.0",
        stages=(5,),
        aliases=("NVIDIA Nemotron-Personas-Korea",),
        code_paths=("src/council/persona_sampler.py", "vault/personas/seeds/korea/agtech-farmers-sample500.jsonl"),
        test_paths=("tests/test_persona_sampler.py", "tests/test_pipeline_reference_artifacts.py"),
        implementation_notes="Local sampler preserves dataset seed provenance when available and marks synthetic fallback when not.",
        license_warning="Dataset-derived outputs need CC-BY-4.0 attribution when used externally.",
        source_url="https://huggingface.co/datasets/nvidia/Nemotron-Personas-Korea",
    ),
    ReferenceInventoryItem(
        name="HACHIMI",
        category=CATEGORY_CLEAN_ROOM,
        license="unknown",
        stages=(5,),
        aliases=("HACHIMI 페르소나 생성",),
        code_paths=("src/council/persona_generator.py", "src/council/persona_prompts.py"),
        test_paths=("tests/test_persona_generator.py", "tests/test_persona_generator_llm.py", "tests/test_pipeline_reference_artifacts.py"),
        implementation_notes="Persona propose/validate/repair loop is implemented locally.",
    ),
    ReferenceInventoryItem(
        name="MAP-Elites",
        category=CATEGORY_CLEAN_ROOM,
        license="algorithmic pattern",
        stages=(5,),
        aliases=("EvoAgentX / MAP-Elites 다양성",),
        code_paths=("src/council/diversity_mapper.py",),
        test_paths=("tests/test_diversity_mapper.py", "tests/test_pipeline_reference_artifacts.py"),
        implementation_notes="Local diversity grid keeps representative personas across risk and innovation axes.",
    ),
    ReferenceInventoryItem(
        name="ReACT 보고서 작성 패턴",
        category=CATEGORY_PARTIAL_PORT,
        license="pattern; verify source before copying more",
        stages=(6,),
        code_paths=("src/search/react-report.py", "src/pipeline/reference_runtime.py", "src/report/composer.py"),
        test_paths=("tests/test_pipeline_reference_artifacts.py", "tests/test_report_composer.py"),
        implementation_notes="Local ReACT planning artifacts are generated from council payloads and included in reports.",
    ),
    ReferenceInventoryItem(
        name="Karpathy LLM Wiki Pattern",
        category=CATEGORY_CLEAN_ROOM,
        license="pattern/gist",
        stages=(6,),
        code_paths=("src/ingest/muchanipo-ingest.py", "src/wiki/dream_cycle.py", "src/pipeline/idea_to_council.py"),
        test_paths=("tests/test_dream_cycle.py", "tests/test_pipeline_reference_artifacts.py"),
        implementation_notes="Local raw/source and wiki/vault output separation follows the LLM wiki pattern.",
        gap="Strict raw/wiki dual-path governance is partial and not yet enforced across every stage-6 artifact.",
        source_url="https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f",
    ),
    ReferenceInventoryItem(
        name="GBrain",
        category=CATEGORY_PARTIAL_PORT,
        license="documented Apache-2.0; verify pinned revision before copying more",
        stages=(6,),
        aliases=("GBrain compiled truth",),
        code_paths=("src/hitl/vault-router.py", "src/wiki/dream_cycle.py", "src/pipeline/reference_runtime.py"),
        test_paths=("tests/test_pipeline_reference_artifacts.py", "tests/test_dream_cycle.py"),
        implementation_notes="Compiled truth, timeline, dedup/hash, and vault persistence patterns are local ports.",
        license_warning=GBRAIN_LICENSE_WARNING,
        source_url="https://github.com/garrytan/gbrain",
    ),
    ReferenceInventoryItem(
        name="GStack retro",
        category=CATEGORY_CLEAN_ROOM,
        license="unknown",
        stages=(6,),
        aliases=("GStack", "retro"),
        code_paths=("src/intent/retro.py",),
        test_paths=("tests/test_learnings_log_and_retro.py", "tests/test_pipeline_reference_artifacts.py"),
        implementation_notes="Local retrospective extraction turns run outcomes into learning records.",
        source_url="https://github.com/garrytan/gstack",
    ),
    ReferenceInventoryItem(
        name="GStack learnings_log",
        category=CATEGORY_CLEAN_ROOM,
        license="unknown",
        stages=(6,),
        aliases=("GStack", "learnings_log"),
        code_paths=("src/intent/learnings_log.py",),
        test_paths=("tests/test_learnings_log_and_retro.py", "tests/test_pipeline_reference_artifacts.py"),
        implementation_notes="Local append-only learning log records reusable observations after pipeline completion.",
        source_url="https://github.com/garrytan/gstack",
    ),
    ReferenceInventoryItem(
        name="플러그인 슬롯 로더 / 런타임 확장 지점",
        category=CATEGORY_CLEAN_ROOM,
        license="local implementation",
        stages=(),
        code_paths=("src/runtime/plugin_loader.py", "config/plugin-slots.yaml"),
        test_paths=("tests/test_plugin_loader.py",),
        implementation_notes="Local slot loader provides runtime extension points for model router/runtime/notifier.",
    ),
    ReferenceInventoryItem(
        name="Codex Skills / Awesome Codex Skills",
        category=CATEGORY_CONCEPT_ONLY,
        license="varies by skill",
        stages=(),
        code_paths=(),
        test_paths=("tests/test_skill_paths.py",),
        implementation_notes="Referenced as an agent-packaging model; Muchanipo remains a real CLI/TUI product.",
        gap="Create a separate skill wrapper only after CLI behavior is stable.",
        source_url="https://github.com/ComposioHQ/awesome-codex-skills",
    ),
    ReferenceInventoryItem(
        name="Claude, Gemini, Codex, Kimi CLI 제공자",
        category=CATEGORY_EXTERNAL,
        license="provider terms",
        stages=(),
        code_paths=(
            "src/execution/providers/anthropic.py",
            "src/execution/providers/gemini.py",
            "src/execution/providers/codex.py",
            "src/execution/providers/kimi.py",
            "src/execution/providers/cli_policy.py",
        ),
        test_paths=("tests/test_provider_anthropic.py", "tests/test_provider_gemini.py", "tests/test_provider_codex.py", "tests/test_provider_kimi.py"),
        implementation_notes="Local provider adapters call installed CLIs/API routes while each provider owns auth/session files.",
    ),
    ReferenceInventoryItem(
        name="OpenRouter, Ollama, 로컬 모델 실행 환경",
        category=CATEGORY_EXTERNAL,
        license="provider/runtime terms",
        stages=(),
        code_paths=("src/execution/providers/openai.py", "src/execution/providers/ollama.py", "src/execution/gateway_v2.py"),
        test_paths=("tests/test_execution_real_wire.py", "tests/test_model_gateway_routing.py"),
        implementation_notes="Fallback model gateway and local provider adapters are implemented as runtime alternatives.",
    ),
)


def reference_inventory(*, repo_root: Path | None = None) -> list[dict[str, Any]]:
    _validate_inventory()
    return [item.as_dict(repo_root=repo_root) for item in REFERENCE_INVENTORY]


def reference_readiness_report(*, repo_root: Path | None = None) -> dict[str, Any]:
    root = repo_root or Path(__file__).resolve().parents[2]
    references = reference_inventory(repo_root=root)
    gaps = [
        {"name": item["name"], "gap": item["gap"]}
        for item in references
        if item.get("gap")
    ]
    license_warnings = _license_warnings(references)
    return {
        "schema_version": 1,
        "command": "muchanipo references",
        "stages": _stage_summaries(references),
        "references": references,
        "gaps": gaps,
        "license_warnings": license_warnings,
        "valid_categories": list(VALID_CATEGORIES),
    }


def _stage_summaries(references: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for contract in CONTRACTS:
        refs = [item for item in references if contract.step in item["stages"]]
        summaries.append(
            {
                "step": contract.step,
                "name": contract.name,
                "runtime_stages": [stage.value for stage in contract.stages],
                "reference_count": len(refs),
                "implemented_count": sum(1 for item in refs if item["implemented"]),
                "gap_count": sum(1 for item in refs if item["gap"]),
                "references": [item["name"] for item in refs],
            }
        )
    return summaries


def _license_warnings(references: list[dict[str, Any]]) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in references:
        warning = str(item.get("license_warning") or "")
        if not warning or warning in seen:
            continue
        seen.add(warning)
        warnings.append({"name": str(item["name"]), "warning": warning})
    return warnings


def _existing_paths(paths: tuple[str, ...], *, repo_root: Path | None) -> list[str]:
    if repo_root is None:
        return []
    existing: list[str] = []
    for path in paths:
        if (repo_root / path).exists():
            existing.append(path)
    return existing


def _validate_inventory() -> None:
    invalid = [item for item in REFERENCE_INVENTORY if item.category not in VALID_CATEGORIES]
    if invalid:
        names = ", ".join(item.name for item in invalid)
        raise ValueError(f"invalid reference inventory categories: {names}")
