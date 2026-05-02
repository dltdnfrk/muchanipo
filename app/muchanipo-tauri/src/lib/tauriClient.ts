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
  // research_progress
  status?: string;
  run_id?: string;
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
    }
  | { action: "approve_designdoc" }
  | { action: "abort" };

// Pipeline mode passed to the Python pipeline.
//   - "stub" : legacy 4-phase placeholder (interview Q&A, single chapter).
//   - "full" : PRD-v2 §2.1 8-stage MBB pipeline (10 council rounds → 6 chapters).
export type PipelineMode = "stub" | "full";
export type ResearchDepth = "shallow" | "deep" | "max";

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
): Promise<void> {
  return invoke("start_pipeline", { topic, pipeline, depth, envs });
}

/**
 * Subscribe to backend events emitted by the Python pipeline.
 * Each line emitted by the server arrives here as a `BackendEvent`.
 */
export async function onBackendEvent(
  handler: (e: BackendEvent) => void,
): Promise<UnlistenFn> {
  return listen<BackendEvent>("backend_event", ({ payload }) => {
    handler(payload);
  });
}

/**
 * Send a user action back into the Python pipeline (e.g. interview answer,
 * approval, or abort). Mirrors the JSON-line action protocol.
 */
export async function sendAction(action: BackendAction): Promise<void> {
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
  return invoke<CliStatus[]>("check_cli_status");
}

/** Execute a tiny real CLI prompt to verify auth + native runtime health. */
export async function checkCliSmoke(name: string): Promise<CliSmokeResult> {
  return invoke<CliSmokeResult>("check_cli_smoke", { name });
}

/** Open the provider's interactive CLI auth flow in Terminal. */
export async function openCliAuth(name: string): Promise<CliAuthLaunch> {
  return invoke<CliAuthLaunch>("open_cli_auth", { name });
}

/**
 * Fetch every JSON-line event the Python pipeline has emitted since the
 * current run started. Used by RunProgress to replay history when the page
 * is re-mounted (e.g. user navigated away and clicked the run from the
 * sidebar) so the stage list reflects actual pipeline state.
 */
export async function getBufferedEvents(): Promise<BackendEvent[]> {
  const lines = await invoke<string[]>("get_buffered_events");
  const out: BackendEvent[] = [];
  for (const line of lines) {
    try {
      out.push(JSON.parse(line) as BackendEvent);
    } catch {
      /* skip malformed lines */
    }
  }
  return out;
}

export async function getPipelineRuntimeStatus(): Promise<PipelineRuntimeStatus> {
  return invoke<PipelineRuntimeStatus>("pipeline_runtime_status");
}

// Legacy alias kept for existing UI components.
export const onMuchanipoEvent = onBackendEvent;
