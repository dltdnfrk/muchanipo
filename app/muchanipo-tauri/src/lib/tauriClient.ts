import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

// Backend event shape — matches src-tauri/src/events.rs BackendEvent.
// Server emits flat JSON-line objects with `event` + arbitrary other fields.
export interface BackendEvent {
  event: string;
  // Common optional fields the server emits.
  stage?: string;
  phase?: string;
  round?: number;
  layer?: string;
  persona?: string;
  delta?: string;
  score?: number;
  message?: string;
  data?: Record<string, unknown>;
  // report_chunk
  chapter_no?: number;
  title?: string;
  markdown?: string;
  source_layers?: string[];
  // final_report
  report_path?: string;
  chapter_count?: number;
  // interview_question
  q_id?: string;
  question_id?: string;
  text?: string;
  prompt?: string;
  options?: unknown[];
  allow_other?: boolean;
  multiSelect?: boolean;
  multi_select?: boolean;
  header?: string;
  preview?: string;
  index?: number;
  total?: number;
  // hitl_gate
  gate?: string;
  // deep_interview_progress
  mode?: string;
  research_type?: string;
  rationale?: string;
  coverage_score?: number;
  ambiguity_score?: number;
  missing_dimensions?: string[];
  focus_dimension?: string;
  focus_label?: string;
  focus_question?: string;
  // deep_interview_artifacts
  workflow?: string;
  workflow_commit?: string;
  document_count?: number;
  document_outputs?: string[];
  evidence_markers?: string[];
  // research_progress
  status?: string;
  run_id?: string;
  app_run_id?: string;
  started_at?: string;
  python_pid?: number;
  python_executable?: string;
  cwd?: string;
  elapsed_sec?: number;
  detail?: string;
  query?: string;
  query_index?: number;
  query_count?: number;
  backends?: string[];
  source_title?: string | null;
  source_url?: string | null;
  source_grade?: string | null;
  source_kind?: string | null;
  access_status?: string | null;
  accepted?: boolean;
  facet_ids?: string[];
  relevance_score?: number;
  reason?: string;
  facet_id?: string;
  accepted_count?: number;
  min_accepted_sources?: number;
  gap_count?: number;
  // council progress
  active_persona_count?: number;
  active_persona_ids?: string[];
  council_stage?: string;
  provider?: string;
  prompt_chars?: number;
  response_chars?: number;
  stopped?: boolean;
  stop_reason?: string;
  visualization_source?: string;
  visualizer_provider?: string;
  visualizer_model?: string;
  visualizer_error?: string;
  // catch-all
  [key: string]: unknown;
}

export type BackendAction =
  | {
      action: "interview_answer";
      choice?: string;
      q_id?: string;
      question_id?: string;
      answer?: string;
      selected?: string;
      other_text?: string;
    }
  | {
      action: "hitl_decision";
      gate: string;
      status: "approved" | "changes_requested";
      comment?: string;
      annotations?: Record<string, unknown>[];
    }
  | { action: "approve_designdoc" }
  | { action: "abort" };

// Pipeline mode passed to the Python pipeline.
//   - "stub" : legacy 4-phase placeholder (interview Q&A, single chapter).
//   - "full" : PRD-v2 §2.1 8-stage MBB pipeline (10 council rounds → 6 chapters).
export type PipelineMode = "stub" | "full";
export type ResearchDepth = "shallow" | "deep" | "max";

function isTauriRuntime(): boolean {
  if (typeof window === "undefined") return false;
  const tauriWindow = window as Window & {
    __TAURI__?: unknown;
    __TAURI_INTERNALS__?: unknown;
  };
  return Boolean(tauriWindow.__TAURI__ || tauriWindow.__TAURI_INTERNALS__);
}

function tauriOnlyError(action: string): Error {
  return new Error(`${action}은 Tauri 데스크톱 앱에서만 사용할 수 있습니다.`);
}

export interface SCR {
  situation: string;
  complication: string;
  resolution: string;
}

export interface Chapter {
  chapter_no: number;
  title: string;
  lead_claim: string;
  body_claims: string[];
  source_layers: string[];
  scr?: SCR;
  framework?: string;
  confidence?: number;
}

export interface FinalReport {
  report_path: string;
  chapter_count: number;
  markdown: string;
}

export interface PipelineRuntimeStatus {
  running: boolean;
  stdin_open?: boolean;
  child_tracked?: boolean;
  buffered_event_count?: number;
  child_pid?: number | null;
  app_run_id?: string | null;
  runtime_age_ms?: number | null;
  last_event_elapsed_ms?: number | null;
  app_binary_path?: string | null;
  workspace_root?: string;
}

/**
 * Start the Python pipeline. Defaults to the full PRD-v2 pipeline so the UI
 * gets a real 6-chapter MBB report.
 */
export async function submitIdea(
  topic: string,
  pipeline: PipelineMode = "full",
  depth: ResearchDepth = "deep",
  envs?: Record<string, string>,
  appRunId?: string,
): Promise<void> {
  if (!isTauriRuntime()) throw tauriOnlyError("리서치 실행");
  return invoke("start_pipeline", { topic, pipeline, depth, envs, appRunId });
}

/**
 * Subscribe to backend events emitted by the Python pipeline.
 * Each line emitted by the server arrives here as a `BackendEvent`.
 */
export async function onBackendEvent(
  handler: (e: BackendEvent) => void,
  appRunId?: string,
): Promise<UnlistenFn> {
  if (!isTauriRuntime()) {
    void handler;
    return () => {};
  }
  return listen<BackendEvent>("backend_event", ({ payload }) => {
    if (appRunId && !isBackendEventForAppRunId(payload, appRunId)) return;
    handler(payload);
  });
}

function isBackendEventForAppRunId(event: BackendEvent, appRunId: string): boolean {
  return String(event.app_run_id ?? "") === appRunId;
}

/**
 * Send a user action back into the Python pipeline (e.g. interview answer,
 * approval, or abort). Mirrors the JSON-line action protocol.
 */
export async function sendAction(action: BackendAction): Promise<void> {
  if (!isTauriRuntime()) throw tauriOnlyError("파이프라인 응답 전송");
  return invoke("send_action", { action });
}

export interface CliStatus {
  name: string;
  installed: boolean;
  path?: string | null;
  version?: string | null;
  error?: string | null;
  version_timed_out?: boolean;
  pipeline_supported?: boolean;
  smoke_supported?: boolean;
  diagnosis?: string | null;
}

export interface CliSmokeResult {
  name: string;
  ok: boolean;
  output?: string | null;
  error?: string | null;
  timed_out: boolean;
}

export interface CliAuthLaunch {
  name: string;
  command: string;
  login_command: string;
}

/** Probe local CLIs (claude / codex / gemini / kimi / opencode) for availability. */
export async function checkCliStatus(): Promise<CliStatus[]> {
  if (!isTauriRuntime()) {
    return ["claude", "codex", "gemini", "kimi", "opencode"].map((name) => ({
      name,
      installed: false,
      error: "Tauri 데스크톱 앱에서만 로컬 CLI 상태를 확인할 수 있습니다.",
      diagnosis: "브라우저 미리보기는 UI 점검 전용입니다. 실제 pipeline 실행은 Tauri 앱에서 검증하세요.",
      pipeline_supported: false,
      smoke_supported: false,
    }));
  }
  return invoke<CliStatus[]>("check_cli_status");
}

/** Execute a tiny real CLI prompt to verify auth + native runtime health. */
export async function checkCliSmoke(name: string): Promise<CliSmokeResult> {
  if (!isTauriRuntime()) {
    return {
      name,
      ok: false,
      output: null,
      error: "Tauri 데스크톱 앱에서만 실호출 테스트를 실행할 수 있습니다.",
      timed_out: false,
    };
  }
  return invoke<CliSmokeResult>("check_cli_smoke", { name });
}

/** Open the provider's interactive CLI auth flow in Terminal. */
export async function openCliAuth(name: string): Promise<CliAuthLaunch> {
  if (!isTauriRuntime()) throw tauriOnlyError(`${name} CLI 연결`);
  return invoke<CliAuthLaunch>("open_cli_auth", { name });
}

/**
 * Fetch every JSON-line event the Python pipeline has emitted since the
 * current run started. Used by RunProgress to replay history when the page
 * is re-mounted (e.g. user navigated away and clicked the run from the
 * sidebar) so the stage list reflects actual pipeline state.
 */
export async function getBufferedEvents(appRunId?: string): Promise<BackendEvent[]> {
  if (!isTauriRuntime()) return [];
  const lines = await invoke<string[]>("get_buffered_events", { appRunId });
  const out: BackendEvent[] = [];
  for (const line of lines) {
    try {
      const event = JSON.parse(line) as BackendEvent;
      if (appRunId && !isBackendEventForAppRunId(event, appRunId)) continue;
      out.push(event);
    } catch {
      /* skip malformed lines */
    }
  }
  return out;
}

export async function getPipelineRuntimeStatus(): Promise<PipelineRuntimeStatus> {
  if (!isTauriRuntime()) {
    return {
      running: false,
      stdin_open: false,
      child_tracked: false,
      buffered_event_count: 0,
      child_pid: null,
      runtime_age_ms: null,
      last_event_elapsed_ms: null,
    };
  }
  return invoke<PipelineRuntimeStatus>("pipeline_runtime_status");
}

// Legacy alias kept for existing UI components.
export const onMuchanipoEvent = onBackendEvent;
