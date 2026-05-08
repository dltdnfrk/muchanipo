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
GAP_PARTIAL_MINIFIED = "partial/minified behavior"
GAP_LICENSE_BLOCKED = "license/compliance blocked"
GAP_TEST_ONLY = "test-only claim"
GAP_DOC_MISMATCH = "doc/inventory mismatch"
GBRAIN_LICENSE = "MIT"
SHOW_PRD_LICENSE_WARNING = (
    "show-me-the-prd declares MIT in upstream metadata but the pinned repository "
    "does not include a standalone LICENSE file; do not distribute vendored prompt "
    "material without preserving upstream metadata or adding the complete notice."
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
    gap_type: str = ""
    license_warning: str = ""
    source_url: str = ""

    def as_dict(self, *, repo_root: Path | None = None) -> dict[str, Any]:
        implemented = bool(self.code_paths) and self.category != CATEGORY_CONCEPT_ONLY
        ready = implemented and not self.gap
        product_standard_covered = ready or _is_explicit_license_boundary(self.gap_type)
        return {
            "name": self.name,
            "aliases": list(self.aliases),
            "category": self.category,
            "license": self.license,
            "stages": list(self.stages),
            "code_paths": list(self.code_paths),
            "test_paths": list(self.test_paths),
            "implemented": implemented,
            "ready": ready,
            "product_standard_covered": product_standard_covered,
            "product_standard_reason": _product_standard_reason(
                ready=ready,
                gap_type=self.gap_type,
                gap=self.gap,
            ),
            "claim_level": _claim_level(
                category=self.category,
                implemented=implemented,
                ready=ready,
                gap=self.gap,
                license_warning=self.license_warning,
            ),
            "blocked_reason": _blocked_reason(
                category=self.category,
                gap=self.gap,
            ),
            "present_paths": _existing_paths(self.code_paths, repo_root=repo_root),
            "implementation_notes": self.implementation_notes,
            "gap": self.gap,
            "gap_type": self.gap_type,
            "license_warning": self.license_warning,
            "source_url": self.source_url,
        }


REFERENCE_INVENTORY: tuple[ReferenceInventoryItem, ...] = (
    ReferenceInventoryItem(
        name="GPTaku show-me-the-prd",
        category=CATEGORY_VENDORED,
        license="MIT",
        stages=(1,),
        aliases=("GPTaku show-me-the-prd",),
        code_paths=(
            "third_party/show-me-the-prd/UPSTREAM.md",
            "third_party/show-me-the-prd/.claude-plugin/plugin.json",
            "third_party/show-me-the-prd/commands/show-me-the-prd.md",
            "third_party/show-me-the-prd/skills/show-me-the-prd/SKILL.md",
            "third_party/show-me-the-prd/skills/show-me-the-prd/references/document-templates.md",
            "third_party/show-me-the-prd/skills/show-me-the-prd/references/interview-guide.md",
            "third_party/show-me-the-prd/skills/show-me-the-prd/references/research-strategy.md",
            "src/interview/show_me_the_prd_port.py",
            "src/intent/interview_prompts.py",
            "src/interview/session.py",
            "src/interview/brief.py",
        ),
        test_paths=(
            "tests/test_show_me_the_prd_port.py",
            "tests/test_interview_prompts.py",
            "tests/test_interview_rubric.py",
            "tests/test_pipeline_reference_artifacts.py",
        ),
        implementation_notes=(
            "The MIT upstream GPTaku show-me-the-prd plugin is vendored at commit "
            "7b22b070a685115a8687ea95fb95d398e4daf043.  "
            "src/interview/show_me_the_prd_port.py exposes its interview, research-batch, "
            "feature/MVP, data-model, phase, stack/auth, and four-document workflow as "
            "runtime evidence before ResearchBrief creation. The JSONL server executes "
            "the in-app deep-interview flow, emits show-me-the-prd research-batch "
            "progress, renders PRD/01_PRD.md, PRD/02_DATA_MODEL.md, PRD/03_PHASES.md, "
            "and PRD/04_PROJECT_SPEC.md from live answers, and the Tauri app displays "
            "the document manifest during the run."
        ),
        license_warning=SHOW_PRD_LICENSE_WARNING,
        source_url="https://github.com/fivetaku/show-me-the-prd",
    ),
    ReferenceInventoryItem(
        name="GStack office-hours",
        category=CATEGORY_CLEAN_ROOM,
        license="MIT",
        stages=(1,),
        code_paths=("src/intent/office_hours.py",),
        test_paths=("tests/intent/test_office_hours.py", "tests/test_office_hours.py"),
        implementation_notes="Local office-hours analysis separates hidden assumptions and research framing from PRD intake.",
        source_url="https://github.com/garrytan/gstack",
    ),
    ReferenceInventoryItem(
        name="GStack plan-review",
        category=CATEGORY_CLEAN_ROOM,
        license="MIT",
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
        implementation_notes="Local adapters query or normalize academic sources and preserve DOI/journal/institution provenance when upstream responses provide it; OpenAlex targeting helpers provide institutions/journals/seed papers, with live seed-paper fallback through the six-source academic sync search.",
        source_url="https://openalex.org",
    ),
    ReferenceInventoryItem(
        name="GBrain 지식 구조",
        category=CATEGORY_CLEAN_ROOM,
        license=GBRAIN_LICENSE,
        stages=(2,),
        aliases=("GBrain",),
        code_paths=(
            "src/wiki/gbrain_runtime.py",
            "src/hitl/vault-router.py",
            "src/wiki/dream_cycle.py",
            "src/pipeline/reference_runtime.py",
        ),
        test_paths=(
            "tests/test_gbrain_runtime.py",
            "tests/test_dream_cycle.py",
            "tests/test_muchanipo_terminal.py",
            "tests/test_pipeline_reference_artifacts.py",
        ),
        implementation_notes=(
            "Local GBrain runtime now builds the stage knowledge structure as a real "
            "compiled-truth page with canonical slug, source IDs, event ledger, typed "
            "links, search index, stale-state policy, and brain-first route. The "
            "current upstream license was verified as MIT during the 2026-05-02 audit; "
            "no AGPL-style license boundary is used for GBrain claims."
        ),
        source_url="https://github.com/garrytan/gbrain",
    ),
    ReferenceInventoryItem(
        name="Plannotator",
        category=CATEGORY_VENDORED,
        license="MIT OR Apache-2.0",
        stages=(2, 4),
        code_paths=(
            "third_party/plannotator/UPSTREAM.md",
            "third_party/plannotator/LICENSE-MIT",
            "third_party/plannotator/LICENSE-APACHE",
            "third_party/plannotator/packages/editor/App.tsx",
            "third_party/plannotator/packages/ui/components/Viewer.tsx",
            "third_party/plannotator/packages/ui/components/AnnotationPanel.tsx",
            "third_party/plannotator/packages/ui/components/AnnotationToolstrip.tsx",
            "third_party/plannotator/packages/ui/utils/parser.ts",
            "third_party/plannotator/packages/ui/types.ts",
            "app/muchanipo-tauri/src/components/PlannotatorPlanEditor.tsx",
            "app/muchanipo-tauri/src/plannotator-port/parser.ts",
            "app/muchanipo-tauri/src/plannotator-port/types.ts",
            "app/muchanipo-tauri/src/plannotator-port/feedback-templates.ts",
            "src/hitl/plannotator_adapter.py",
            "src/hitl/plannotator_http.py",
        ),
        test_paths=(
            "tests/test_plan_review_inline_edits.py",
            "tests/test_plannotator_adapter.py",
            "tests/test_plannotator_http.py",
            "tests/test_pipeline_reference_artifacts.py",
        ),
        implementation_notes=(
            "The MIT-or-Apache upstream Plannotator source is vendored at commit "
            "6324a0c859f06030b47d71c02b7c6fed09fa0b92. The Tauri app embeds copied "
            "Plannotator parser/types/feedback code plus a local plan editor port that "
            "preserves the upstream block/annotation/export model inside the Muchanipo "
            "plan HITL gate, so plan edits happen in-app and are applied before targeting. "
            "The port uses Plannotator exportAnnotations, exportLinkedDocAnnotations, "
            "wrapFeedbackForAgent, parser blocks, annotation panel state, and strict "
            "plan-edit payloads. HTTP Plannotator remains an optional adapter. The "
            "upstream workspace under third_party/plannotator is source evidence only; "
            "production code must use the constrained Tauri port unless the upstream "
            "dependency tree is separately audited."
        ),
        source_url="https://github.com/backnotprop/plannotator",
    ),
    ReferenceInventoryItem(
        name="Karpathy Autoresearch",
        category=CATEGORY_PARTIAL_PORT,
        license="MIT declared in upstream README; no standalone LICENSE in pinned snapshot",
        stages=(3,),
        code_paths=(
            "third_party/karpathy-autoresearch/program.md",
            "third_party/karpathy-autoresearch/prepare.py",
            "third_party/karpathy-autoresearch/train.py",
            "src/research/karpathy_autoresearch.py",
        ),
        test_paths=(
            "tests/test_research_real_wire.py",
            "tests/test_pipeline_runner.py",
            "tests/test_pipeline_reference_artifacts.py",
        ),
        implementation_notes=(
            "Pinned upstream source is vendored under third_party, and source-research "
            "mode executes a faithful local keep/discard adapter: write program.md and "
            "results.tsv, evaluate a fixed lower-is-better grounding metric, keep strict "
            "improvements, and discard non-improvements. The experiment surface is "
            "ResearchPlan.queries rather than upstream train.py; git reset is replaced "
            "with scratch retention to protect the user's worktree."
        ),
        license_warning=(
            "Pinned upstream README declares MIT, but the local snapshot has no standalone "
            "LICENSE file. Preserve third_party/karpathy-autoresearch/UPSTREAM.md and "
            "review external release packaging."
        ),
        source_url="https://github.com/karpathy/autoresearch",
    ),
    ReferenceInventoryItem(
        name="InsightForge",
        category=CATEGORY_PARTIAL_PORT,
        license="AGPL-3.0 upstream; local adaptation must preserve compliance boundaries",
        stages=(3,),
        code_paths=("src/search/insight-forge.py", "src/research/queries.py"),
        test_paths=(
            "tests/test_insight_forge_dedup.py",
            "tests/test_c31_research_evidence.py",
            "tests/test_react_report_executor.py",
        ),
        implementation_notes=(
            "Local InsightForge runtime performs MiroFish-style subquery generation, "
            "main query search, MemPalace semantic lookup, RRF fusion, 4-layer dedup, "
            "stale markers, entity insight extraction, relationship-chain extraction, "
            "and ReACT backend execution. It is ready as an AGPL-sensitive local "
            "adaptation, not as permission to copy more upstream material."
        ),
        license_warning=(
            "InsightForge is derived from the AGPL-3.0 MiroFish family; preserve AGPL "
            "source availability and notices for copied/adapted material."
        ),
        source_url="https://github.com/666ghj/MiroFish",
    ),
    ReferenceInventoryItem(
        name="MemPalace",
        category=CATEGORY_CLEAN_ROOM,
        license="MIT upstream; local stdlib implementation",
        stages=(3,),
        code_paths=("src/research/mempalace.py", "src/research/runner.py", "src/search/insight-forge.py"),
        test_paths=(
            "tests/test_mempalace_runtime.py",
            "tests/test_research_real_wire.py",
            "tests/test_pipeline_reference_artifacts.py",
        ),
        implementation_notes=(
            "Local MemPalace-style runtime indexes markdown memory roots by wing, room, "
            "source path, score, and snippet. WebResearchRunner records backend trace and "
            "only marks MemPalace executed when vault/InsightForge memory backends actually "
            "run or produce memory evidence. The runtime can also persist source-backed "
            "memory notes into wing/room storage and build a searchable manifest with "
            "hashes, rooms, wings, and record metadata."
        ),
        source_url="https://github.com/MemPalace/mempalace",
    ),
    ReferenceInventoryItem(
        name="GBrain 현재 결론 + 사건 기록",
        category=CATEGORY_CLEAN_ROOM,
        license=GBRAIN_LICENSE,
        stages=(4,),
        aliases=("현재 결론 + 사건 기록",),
        code_paths=(
            "src/wiki/gbrain_runtime.py",
            "src/hitl/vault-router.py",
            "src/pipeline/reference_runtime.py",
            "src/wiki/dream_cycle.py",
        ),
        test_paths=(
            "tests/test_gbrain_runtime.py",
            "tests/test_pipeline_reference_artifacts.py",
            "tests/test_dream_cycle.py",
        ),
        implementation_notes=(
            "Current conclusion is extracted from compiled truth, and the event record "
            "is an append-only ledger with evidence verification, timeline, and council "
            "synthesis events. This is a runnable local adaptation of GBrain's current "
            "truth plus event-stream model."
        ),
        source_url="https://github.com/garrytan/gbrain",
    ),
    ReferenceInventoryItem(
        name="출처 기반 연구 원칙",
        category=CATEGORY_CLEAN_ROOM,
        license="project policy",
        stages=(4,),
        code_paths=("src/evidence/store.py", "src/evidence/provenance.py", "src/eval/citation_grounder.py"),
        test_paths=("tests/test_research_real_wire.py", "tests/test_citation_grounder.py", "tests/test_live_product_gate.py"),
        implementation_notes="Evidence references pass stdlib structural provenance checks plus optional lockdown validation; live-mode gates and provenance failures are enforced by local tests.",
    ),
    ReferenceInventoryItem(
        name="MiroFish",
        category=CATEGORY_PARTIAL_PORT,
        license="AGPL-3.0",
        stages=(5,),
        aliases=("MiroFish Crowd Intelligence",),
        code_paths=(
            "src/agents/mirofish.py",
            "src/council/council-runner.py",
            "src/search/insight-forge.py",
            "src/search/react-report.py",
        ),
        test_paths=(
            "tests/test_mirofish_runtime.py",
            "tests/test_council_real_wire.py",
            "tests/test_council_session_llm.py",
            "tests/test_pipeline_reference_artifacts.py",
        ),
        implementation_notes=(
            "Stage 5 emits a real local MiroFish-style swarm runtime record: seed "
            "evidence and topic become a world graph, personas become configured "
            "agents with memory, council turns become simulation events and temporal "
            "memory updates, and the report/council transcript provides report-agent "
            "and deep-interaction surfaces. The full upstream repository is not "
            "vendored; additional upstream copying remains a compliance decision."
        ),
        license_warning=(
            "MiroFish is AGPL-3.0; preserve notices for copied/adapted material and "
            "do not vendor additional upstream code, prompts, schemas, or report "
            "templates without a dedicated compliance review."
        ),
        source_url="https://github.com/666ghj/MiroFish",
    ),
    ReferenceInventoryItem(
        name="OASIS / CAMEL-AI",
        category=CATEGORY_CLEAN_ROOM,
        license="Apache-2.0 or project-specific; verify upstream component before copying code",
        stages=(5,),
        aliases=("OASIS", "CAMEL-AI"),
        code_paths=(
            "src/council/oasis_camel_runtime.py",
            "src/council/session.py",
            "src/council/prompts.py",
            "src/council/round_layers.py",
        ),
        test_paths=("tests/test_council_session_llm.py", "tests/test_council_real_wire.py", "tests/test_pipeline_reference_artifacts.py"),
        implementation_notes=(
            "Council protocol is represented as a clean-room OASIS/CAMEL-style "
            "local social simulation: individual private analysis, blinded peer "
            "review, chair synthesis, world state, per-agent memory, and interaction "
            "events with explicit output contracts. No upstream runtime is vendored."
        ),
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
        license="MIT",
        stages=(5,),
        aliases=("HACHIMI 페르소나 생성",),
        code_paths=("src/council/persona_generator.py", "src/council/persona_prompts.py"),
        test_paths=("tests/test_persona_generator.py", "tests/test_persona_generator_llm.py", "tests/test_pipeline_reference_artifacts.py"),
        implementation_notes=(
            "Local HACHIMI runtime implements propose/fast-validate/revise/deep-validate, "
            "schema/value-axis checks, optional LLM judge prompts, Korean PII/name safety "
            "guards, role quota telemetry, and SimHash-style deduplication before final "
            "persona admission."
        ),
        source_url="https://github.com/ZeroLoss-Lab/HACHIMI",
    ),
    ReferenceInventoryItem(
        name="MAP-Elites",
        category=CATEGORY_CLEAN_ROOM,
        license="algorithmic pattern; EvoAgentX source MIT",
        stages=(5,),
        aliases=("EvoAgentX / MAP-Elites 다양성",),
        code_paths=("src/council/diversity_mapper.py",),
        test_paths=("tests/test_diversity_mapper.py", "tests/test_pipeline_reference_artifacts.py"),
        implementation_notes="Local diversity grid keeps representative personas across risk and innovation axes.",
        source_url="https://github.com/EvoAgentX/EvoAgentX",
    ),
    ReferenceInventoryItem(
        name="ReACT 보고서 작성 패턴",
        category=CATEGORY_PARTIAL_PORT,
        license="pattern; verify source before copying more",
        stages=(6,),
        code_paths=("src/search/react-report.py", "src/pipeline/reference_runtime.py", "src/report/composer.py"),
        test_paths=("tests/test_react_report_executor.py", "tests/test_pipeline_reference_artifacts.py", "tests/test_report_composer.py"),
        implementation_notes=(
            "Local ReACT sections execute parsed tool-call loops; InsightForge, MemPalace, "
            "and academic web_search backends are called when available. The executor also "
            "supports an LLM-driven ReACT responder path and keeps deterministic offline "
            "execution as a no-network fallback. Live/report mode passes the stage "
            "gateway into the ReACT responder, records execution modes and LLM response "
            "counts, and requires live provider results when the run is live-gated."
        ),
        source_url="https://react-lm.github.io",
    ),
    ReferenceInventoryItem(
        name="Karpathy LLM Wiki Pattern",
        category=CATEGORY_CLEAN_ROOM,
        license="pattern/gist",
        stages=(6,),
        code_paths=(
            "src/ingest/muchanipo-ingest.py",
            "src/wiki/dream_cycle.py",
            "src/wiki/governance.py",
            "src/pipeline/reference_runtime.py",
            "src/pipeline/idea_to_council.py",
        ),
        test_paths=("tests/test_wiki_governance.py", "tests/test_dream_cycle.py", "tests/test_pipeline_reference_artifacts.py"),
        implementation_notes=(
            "Local raw/source and wiki/vault output separation follows the LLM wiki pattern. "
            "Stage 6 records raw JSON path, wiki markdown path, search-index path, "
            "manifest path, distinct content hashes, source IDs, outbound links, and "
            "maintenance policy for compiled-truth artifacts."
        ),
        source_url="https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f",
    ),
    ReferenceInventoryItem(
        name="GBrain",
        category=CATEGORY_CLEAN_ROOM,
        license=GBRAIN_LICENSE,
        stages=(6,),
        aliases=("GBrain compiled truth",),
        code_paths=(
            "src/wiki/gbrain_runtime.py",
            "src/hitl/vault-router.py",
            "src/wiki/dream_cycle.py",
            "src/pipeline/reference_runtime.py",
        ),
        test_paths=(
            "tests/test_gbrain_runtime.py",
            "tests/test_pipeline_reference_artifacts.py",
            "tests/test_dream_cycle.py",
        ),
        implementation_notes=(
            "Stage 6 emits a local GBrain runtime record alongside the vault-router "
            "compiled truth and Karpathy raw/wiki governance. The record includes "
            "content hash, append-only timeline/event ledger, typed links, brain-first "
            "lookup route, graph-boosted search index, and maintenance checks."
        ),
        source_url="https://github.com/garrytan/gbrain",
    ),
    ReferenceInventoryItem(
        name="GStack retro",
        category=CATEGORY_CLEAN_ROOM,
        license="MIT",
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
        license="MIT",
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
        name="Claude, Gemini, Codex, Kimi, OpenCode CLI 제공자",
        category=CATEGORY_EXTERNAL,
        license="provider terms",
        stages=(),
        code_paths=(
            "src/execution/providers/anthropic.py",
            "src/execution/providers/gemini.py",
            "src/execution/providers/codex.py",
            "src/execution/providers/kimi.py",
            "src/execution/providers/opencode.py",
            "src/execution/providers/cli_policy.py",
        ),
        test_paths=(
            "tests/test_provider_anthropic.py",
            "tests/test_provider_gemini.py",
            "tests/test_provider_codex.py",
            "tests/test_provider_kimi.py",
            "tests/test_provider_opencode.py",
        ),
        implementation_notes="Local provider adapters call installed CLIs/API routes while each provider owns auth/session files; OpenCode is called through its CLI or OpenCode Go API fallback without reading local auth files.",
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
        {"name": item["name"], "gap": item["gap"], "gap_type": item["gap_type"]}
        for item in references
        if item.get("gap")
    ]
    not_ready = [
        {
            "name": item["name"],
            "claim_level": item["claim_level"],
            "blocked_reason": item["blocked_reason"],
            "gap_type": item["gap_type"],
            "product_standard_covered": item["product_standard_covered"],
            "product_standard_reason": item["product_standard_reason"],
        }
        for item in references
        if not item.get("ready")
    ]
    not_stage_contract_covered = [
        {
            "name": item["name"],
            "claim_level": item["claim_level"],
            "blocked_reason": item["blocked_reason"],
            "gap_type": item["gap_type"],
            "product_standard_reason": item["product_standard_reason"],
        }
        for item in references
        if item.get("stages") and not item.get("product_standard_covered")
    ]
    license_warnings = _license_warnings(references)
    return {
        "schema_version": 1,
        "command": "muchanipo references",
        "stages": _stage_summaries(references),
        "references": references,
        "gaps": gaps,
        "not_ready_references": not_ready,
        "not_stage_contract_covered_references": not_stage_contract_covered,
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
                "ready_count": sum(1 for item in refs if item["ready"]),
                "product_standard_covered_count": sum(
                    1 for item in refs if item["product_standard_covered"]
                ),
                "license_blocked_count": sum(
                    1 for item in refs if item["gap_type"] == GAP_LICENSE_BLOCKED
                ),
                "gap_count": sum(1 for item in refs if item["gap"]),
                "not_ready_count": sum(1 for item in refs if not item["ready"]),
                "ready": bool(refs) and all(item["ready"] for item in refs),
                "product_standard_ready": bool(refs)
                and all(item["product_standard_covered"] for item in refs),
                "references": [item["name"] for item in refs],
                "not_ready_references": [item["name"] for item in refs if not item["ready"]],
                "not_product_standard_covered_references": [
                    item["name"] for item in refs if not item["product_standard_covered"]
                ],
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


def _claim_level(
    *,
    category: str,
    implemented: bool,
    ready: bool,
    gap: str,
    license_warning: str,
) -> str:
    if category == CATEGORY_CONCEPT_ONLY:
        return "concept_only"
    if not implemented:
        return "not_implemented"
    if gap:
        return "implemented_with_gap"
    if license_warning:
        return "runtime_with_compliance_warning"
    if ready:
        return "runtime_ready"
    return "not_ready"


def _blocked_reason(*, category: str, gap: str) -> str:
    if gap:
        return gap
    if category == CATEGORY_CONCEPT_ONLY:
        return "concept-only reference; not a product runtime claim"
    return ""


def _is_explicit_license_boundary(gap_type: str) -> bool:
    return gap_type == GAP_LICENSE_BLOCKED


def _product_standard_reason(*, ready: bool, gap_type: str, gap: str) -> str:
    if ready:
        return "runtime_behavior"
    if _is_explicit_license_boundary(gap_type):
        return "explicit_license_boundary"
    if gap:
        return "unresolved_gap"
    return "not_runtime_claim"


def _validate_inventory() -> None:
    invalid = [item for item in REFERENCE_INVENTORY if item.category not in VALID_CATEGORIES]
    if invalid:
        names = ", ".join(item.name for item in invalid)
        raise ValueError(f"invalid reference inventory categories: {names}")
