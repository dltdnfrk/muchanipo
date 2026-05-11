from __future__ import annotations

from pathlib import Path


TAURI_SRC = Path("app/muchanipo-tauri/src")


def test_api_mode_plumbs_opencode_go_key_to_both_supported_env_aliases() -> None:
    source = (TAURI_SRC / "pages" / "RunProgress.tsx").read_text(encoding="utf-8")

    assert 'const opencodeGoKey = readCredential("opencode_api_key").trim();' in source
    assert 'envs.OPENCODE_API_KEY = opencodeGoKey;' in source
    assert 'envs.OPENCODE_GO_API_KEY = opencodeGoKey;' in source


def test_api_mode_allows_either_mimo_or_opencode_go_without_other_providers() -> None:
    source = (TAURI_SRC / "pages" / "RunProgress.tsx").read_text(encoding="utf-8")

    assert "if (!mimoKey && !opencodeGoKey)" in source
    assert 'envs.MUCHANIPO_VERIFICATION_ROUTING = "mimo_opencode_go_only";' in source
    assert 'envs.MIMO_MODEL = readCredential("mimo_model").trim() || "mimo-v2.5-pro";' in source
    assert 'envs.MUCHANIPO_MIMO_MODEL = envs.MIMO_MODEL;' in source
    assert 'envs.XIAOMI_MIMO_BASE_URL = mimoBaseUrl;' in source
    assert 'envs.MUCHANIPO_PROVIDER_CHAIN = opencodeGoKey ? "mimo,opencode" : "mimo";' in source
    assert 'envs.MUCHANIPO_CHAIRMAN_TIMEOUT_FALLBACK = "1";' in source
    assert '"MUCHANIPO_CHAIRMAN_TIMEOUT_FALLBACK"' in (
        Path("app/muchanipo-tauri/src-tauri/src/python_bridge.rs").read_text(encoding="utf-8")
    )
    assert 'envs.OPENCODE_USE_CLI = "0";' in source
    assert 'ANTHROPIC_API_KEY' not in source
    assert 'GEMINI_API_KEY' not in source
    assert 'KIMI_API_KEY' not in source
    assert 'OPENAI_API_KEY' not in source


def test_api_settings_use_documented_mimo_token_plan_defaults() -> None:
    source = (TAURI_SRC / "pages" / "Settings.tsx").read_text(encoding="utf-8")

    assert 'const DEFAULT_MIMO_BASE_URL = "https://token-plan-sgp.xiaomimimo.com/v1";' in source
    assert 'const DEFAULT_MIMO_MODEL = "mimo-v2.5-pro";' in source
    assert 'hint: "기본: mimo-v2.5-pro"' in source


def test_streaming_components_use_backend_event_discriminator() -> None:
    types_source = (TAURI_SRC / "lib" / "types.ts").read_text(encoding="utf-8")
    assert "export function backendEventName" in types_source

    for relative_path in (
        "components/InterviewQuestion.tsx",
        "components/CouncilMonitor.tsx",
        "components/ReportViewer.tsx",
    ):
        source = (TAURI_SRC / relative_path).read_text(encoding="utf-8")
        assert "backendEventName(payload)" in source or "backendEventName(event)" in source
        assert "payload.type ===" not in source
        assert "event.type ===" not in source


def test_tauri_types_include_interview_ontology_delta_event() -> None:
    types_source = (TAURI_SRC / "lib" / "types.ts").read_text(encoding="utf-8")
    tauri_source = (TAURI_SRC / "lib" / "tauri.ts").read_text(encoding="utf-8")

    assert '"interview_ontology_delta"' in tauri_source
    assert '"interview_ontology_delta"' in types_source
    assert "InterviewOntologyDeltaEvent" in types_source
    assert "targets_unknown_ids?: string[]" in types_source
    assert "question_quality_gate?: Record<string, unknown>" in types_source


def test_studio_entry_uses_stable_browser_preview_without_vertical_presets() -> None:
    source = (TAURI_SRC / "pages" / "IdeaSubmit.tsx").read_text(encoding="utf-8")

    for stable_noun in ("Studio", "Browser", "Goal", "Unknown", "Evidence", "Run", "Report"):
        assert stable_noun in source
    assert "Browser preview" in source
    assert "Locked" in source
    assert "Studio graph required" in source
    assert "Start with a Goal." in source
    assert "Describe the Goal in one sentence." in source

    # Domain-specific visible examples should come from the user's goal/backend events,
    # not hardcoded presets in the product chrome.
    for preset in ("딸기 농가", "재택의료 SaaS", "Z세대", "코딩 어시스턴트", "주제 추천", "예시 넣기"):
        assert preset not in source
    for decorative in ("frontier", "magic", "high reasoning", "AI Studio", "AI Browser"):
        assert decorative not in source


def test_browser_run_header_uses_stable_status_label() -> None:
    source = (TAURI_SRC / "pages" / "RunProgress.tsx").read_text(encoding="utf-8")

    assert 'atlas-label mb-2">Browser' in source
    assert "Live Research Run" not in source
    assert "min-w-[72px]" in source
    assert ">Run" in source


def test_studio_session_route_exposes_interview_and_ontology_surfaces() -> None:
    app_source = (TAURI_SRC / "App.tsx").read_text(encoding="utf-8")
    studio_source = (TAURI_SRC / "pages" / "StudioSession.tsx").read_text(encoding="utf-8")

    assert 'path="/studio/:studioId"' in app_source
    assert "Deep Interview" in studio_source
    assert "정리 항목" in studio_source
    assert "Ontology" in studio_source
    assert "Browser에서 실행" in studio_source
    assert "모델 선택" in studio_source
    assert "MODEL_OPTIONS" in studio_source
    assert "Opus 4.6" in studio_source
    assert "Sonnet 4.5" in studio_source
    assert "Haiku 4.5" in studio_source
    assert "claude-composer" in studio_source
    assert "setQuestion(" not in studio_source
    for decorative in ("magic", "AI Studio", "AI Browser", "frontier", "high reasoning"):
        assert decorative not in studio_source


def test_studio_session_exposes_three_layer_persona_plan_from_goal() -> None:
    studio_source = (TAURI_SRC / "pages" / "StudioSession.tsx").read_text(encoding="utf-8")

    assert "PERSONA_PLAN_TEMPLATES" in studio_source
    assert "Persona Plan" in studio_source
    assert "Layer 1 · 직접 사용자" in studio_source
    assert "Layer 2 · 생태계 이해관계자" in studio_source
    assert "Layer 3 · 교차 분야/반대 전문가" in studio_source
    assert "현재 Goal 기준" in studio_source
    assert "{goal}" in studio_source
    for decorative in ("AI persona", "magic", "frontier", "high reasoning"):
        assert decorative not in studio_source


def test_studio_persona_plan_is_bound_to_interview_answers() -> None:
    studio_source = (TAURI_SRC / "pages" / "StudioSession.tsx").read_text(encoding="utf-8")

    assert "buildPersonaPlanLayers" in studio_source
    assert "const personaPlanLayers = useMemo(" in studio_source
    assert "sourceTurnId" in studio_source
    assert "turn.answer?.trim()" in studio_source
    assert "basis" in studio_source
    assert "Basis ·" in studio_source
    assert "Status ·" in studio_source
    assert "personaPlanLayers.map" in studio_source
    assert "PERSONA_PLAN_TEMPLATES.map" not in studio_source


def test_browser_run_exposes_selected_persona_provenance_labels() -> None:
    source = (TAURI_SRC / "pages" / "RunProgress.tsx").read_text(encoding="utf-8")

    assert "PERSONA_PROVENANCE_LABELS" in source
    assert "browserPersonaRows" in source
    assert "Selected personas" in source
    assert "Provenance" in source
    assert "Persona sample pool" in source
    assert "Fallback template" in source
    assert "Backend selected persona" in source
    assert "received from council active_persona_ids" in source
    assert "Diversity sampling" in source
    assert "Council protocol" in source
    assert "pending backend selection" in source
    assert "PERSONA_PROVENANCE_LABELS[index % PERSONA_PROVENANCE_LABELS.length]" not in source
    for preset in ("딸기 농가", "재택의료 SaaS", "Z세대", "AgTech"):
        assert preset not in source


def test_browser_run_escalates_long_backend_silence_to_restart_guidance() -> None:
    source = (TAURI_SRC / "pages" / "RunProgress.tsx").read_text(encoding="utf-8")

    assert "120000" in source
    assert "2분 넘게" in source
    assert "다시 시작" in source


def test_browser_restart_clears_run_scoped_observability_state() -> None:
    source = (TAURI_SRC / "pages" / "RunProgress.tsx").read_text(encoding="utf-8")

    assert "clearRunScopedSessionKeys" in source
    assert "setInterviewArtifacts(null)" in source
    assert "setPlanReviewEdits(null)" in source
    assert "setRuntimeEvidence(null)" in source
    assert '"vault_path"' in source
    assert 'sessionStorage.removeItem(`run:${runId}:pending_session`)' in source
    assert 'key.startsWith(`muchanipo:auto-answer:${runId}:`)' in source
    assert 'key.startsWith(`muchanipo:auto-approve:${runId}:`)' in source


def test_browser_header_surfaces_desktop_live_e2e_evidence_gap() -> None:
    source = (TAURI_SRC / "pages" / "RunProgress.tsx").read_text(encoding="utf-8")

    assert "Desktop/live evidence" in source
    assert "Desktop runtime" in source
    assert "Live e2e" in source
    assert "Not observed yet" in source
    assert "Not proven in this UI session" in source


def test_browser_live_e2e_status_uses_runtime_status_app_run_id() -> None:
    source = (TAURI_SRC / "pages" / "RunProgress.tsx").read_text(encoding="utf-8")

    assert "runId: status.app_run_id ?? prev?.runId" in source
    assert "setHasReceivedHeartbeat(true)" in source
    assert "const hasVisibleBackendHeartbeat = hasReceivedHeartbeat" in source
    assert "Backend run signals observed" in source


def test_dev_autostart_reaches_studio_before_existing_runs_redirect_to_browser() -> None:
    source = (TAURI_SRC / "App.tsx").read_text(encoding="utf-8")

    assert "VITE_MUCHANIPO_AUTOSTART_TOPIC" in source
    assert "autostartTopic ? \"/studio\"" in source
    assert "hasRun ? \"/browser\" : \"/studio\"" in source


def test_browser_home_uses_real_run_topic_not_crop_placeholder() -> None:
    source = (TAURI_SRC / "pages" / "BrowserHome.tsx").read_text(encoding="utf-8")

    assert "runTopic" in source
    assert "{runTopic}" in source
    assert "RunProgress에서 heartbeat/source 확인" in source
    assert "딸기 농가용 저비용 분자진단 키트" not in source
    assert "completedCount" not in source
    assert "/10 단계" not in source
    assert "진행률" not in source
    assert "summary.progress" not in source
    assert "cowork-title-actions" not in source
    assert "Tauri desktop" not in source
    assert "Source research" not in source


def test_run_progress_surfaces_provider_error_as_product_pass_blocker() -> None:
    source = (TAURI_SRC / "pages" / "RunProgress.tsx").read_text(encoding="utf-8")

    assert "blocks_product_pass" in source
    assert "blocksProductPass" in source
    assert "blocks product pass" in source
    assert "provider_call_error" in source
    assert "errorClass" in source


def test_evidence_index_exposes_safe_source_access_status_contract() -> None:
    panel_source = (TAURI_SRC / "components" / "EvidenceIndexPanel.tsx").read_text(encoding="utf-8")
    presentation_source = (TAURI_SRC / "lib" / "reportPresentation.ts").read_text(encoding="utf-8")
    combined = panel_source + presentation_source

    for label in (
        "Full text",
        "Abstract",
        "Open access",
        "Restricted",
        "Alternative",
        "Not reported",
        "Access status",
    ):
        assert label in combined

    assert "accessStatus" in presentation_source
    assert "normalizeAccessStatus" in presentation_source
    assert "paywall bypass" not in combined.lower()
    assert "access-control bypass" not in combined.lower()
    assert "뚫" not in combined


def test_all_source_discovery_files_avoid_bypass_language() -> None:
    """Any file that renders source access status must not contain language that
    suggests paywall or access-control bypass. This is a broad catch-all beyond
    the narrower EvidenceIndexPanel + reportPresentation checks."""
    files_to_scan = (
        TAURI_SRC / "components" / "SourceDiscoveryPanel.tsx",
        TAURI_SRC / "pages" / "ReportView.tsx",
        TAURI_SRC / "pages" / "RunProgress.tsx",
    )
    combined = ""
    for path in files_to_scan:
        assert path.exists(), f"Expected source file {path} to exist"
        combined += path.read_text(encoding="utf-8")

    forbidden_phrases = [
        "paywall bypass",
        "access-control bypass",
        "bypass paywall",
        "bypass access",
        "unlock content",
        "crack access",
        "hack access",
        "circumvent paywall",
        "breach paywall",
    ]
    for phrase in forbidden_phrases:
        assert phrase not in combined.lower(), f"Forbidden phrase {phrase!r} found in source discovery files"

    # Safe labels must be present in the combined surface
    for safe_label in ("Full text", "Abstract", "Open access", "Restricted", "Alternative"):
        assert safe_label in combined, f"Safe label {safe_label!r} must appear in source discovery files"


def test_report_view_fallback_preserves_safe_access_status_labels() -> None:
    """When ReportView patches missing localStorage by parsing Evidence Index markdown,
    it must still surface sources through the safe-label pipeline."""
    source = (TAURI_SRC / "pages" / "ReportView.tsx").read_text(encoding="utf-8")

    assert "parseEvidenceIndex" in source
    assert "accessStatus" in source
    assert "discoveredSources" in source
    assert "SourceDiscoveryPanel" in source
    # Ensure the fallback path does not invent its own labels
    assert "displayAccessStatus" not in source, "ReportView should rely on parsed/normalized accessStatus"


def test_source_discovery_panel_uses_safe_access_status_labels() -> None:
    """SourceDiscoveryPanel is the primary live-discovery UI; it must carry the same
    safe access-status label contract as the report layer."""
    source = (TAURI_SRC / "components" / "SourceDiscoveryPanel.tsx").read_text(encoding="utf-8")

    for safe_label in ("Full text", "Abstract", "Open access", "Restricted", "Alternative", "Not reported"):
        assert safe_label in source, f"Safe label {safe_label!r} must appear in SourceDiscoveryPanel"
    assert "displayAccessStatus" in source
    assert "normalizeSourceAccessStatus" in source
    # Internal canonical values must exist for mapping but should not be rendered raw
    for raw_status in ("full_text_available", "oa_copy_found", "alternative_evidence"):
        assert raw_status in source, f"Canonical status {raw_status!r} must be mapped"


def test_browser_run_renders_backend_persona_pool_telemetry_card() -> None:
    """Browser must surface live Persona Pool telemetry the Python pipeline
    already records (seed source, validation/diversity framework, council
    protocol, pool/fallback counts) — not only the static fallback ladder."""
    component_path = TAURI_SRC / "components" / "PersonaPoolCard.tsx"
    runprogress_path = TAURI_SRC / "pages" / "RunProgress.tsx"
    assert component_path.exists(), "PersonaPoolCard component must exist"

    component_source = component_path.read_text(encoding="utf-8")
    for telemetry_key in (
        "persona_seed_source",
        "persona_validation_framework",
        "persona_diversity_framework",
        "council_protocol",
        "persona_pool_size",
        "persona_pool_target_size",
        "active_persona_count",
        "persona_diversity_coverage",
        "persona_diversity_bins_per_axis",
        "persona_fallbacks_used",
    ):
        assert telemetry_key in component_source, (
            f"PersonaPoolCard must read backend artifact key {telemetry_key!r}"
        )
    for stable_label in ("Persona Pool", "Seed", "Validation", "Diversity", "Council"):
        assert stable_label in component_source
    for decorative in ("magic", "frontier", "AI Pool", "high reasoning"):
        assert decorative not in component_source

    runprogress_source = runprogress_path.read_text(encoding="utf-8")
    assert "PersonaPoolCard" in runprogress_source
    assert "normalizePersonaPoolSummary" in runprogress_source
    assert "<PersonaPoolCard pool={personaPool}" in runprogress_source
    assert "setPersonaPool(null)" in runprogress_source


def test_backend_source_avoids_vertical_hardcoding() -> None:
    """Python backend must not contain crop-specific or vertical-preset hardcoding
    that would make Muchanipo non-general-purpose."""
    src_paths = list(Path("src").rglob("*.py"))
    combined = ""
    for path in src_paths:
        combined += path.read_text(encoding="utf-8")

    # Crop-specific hardcoding that should not exist in general-purpose product code
    crop_presets = ("딸기", "strawberry", "사과", "포도", "grape", "토마토", "tomato")
    for preset in crop_presets:
        assert preset not in combined, f"Crop-specific preset {preset!r} must not be hardcoded in backend source"

    # Decorative AI copy should not exist ("magic link" is a standard auth term and allowed)
    for decorative in ("frontier", "high reasoning", "AI-powered", "superintelligent"):
        assert decorative not in combined.lower(), f"Decorative AI copy {decorative!r} must not be in backend source"
