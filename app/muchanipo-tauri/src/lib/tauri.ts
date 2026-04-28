import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

export type BackendEventName =
  | "phase_change"
  | "interview_question"
  | "council_round_start"
  | "council_persona_token"
  | "council_round_done"
  | "report_chunk"
  | "done"
  | "warning"
  | "error";

export interface BackendEvent {
  event: BackendEventName;
  [key: string]: unknown;
}

export interface BackendAction {
  action?: "interview_answer" | "approve_designdoc" | "abort";
  type?: "interview_answer" | "approve_designdoc" | "cancel" | "abort";
  q_id?: string;
  question_id?: string;
  answer?: string;
  selected?: string;
  other_text?: string;
  [key: string]: unknown;
}

export function startPipeline(
  topic: string,
  pipeline: "stub" | "full" = "full",
  envs: Record<string, string> = {},
): Promise<void> {
  return invoke("start_pipeline", { topic, pipeline, envs });
}

export function sendAction(action: BackendAction): Promise<void> {
  return invoke("send_action", { action: normalizeAction(action) });
}

export function listenBackendEvents(
  onEvent: (event: BackendEvent) => void,
): Promise<UnlistenFn> {
  return listen<BackendEvent>("backend_event", ({ payload }) => {
    onEvent(payload);
  });
}

function normalizeAction(action: BackendAction): BackendAction {
  const normalized: BackendAction = { ...action };

  if (!normalized.action) {
    normalized.action =
      normalized.type === "cancel" ? "abort" : normalized.type ?? "interview_answer";
  }

  if (!normalized.q_id && typeof normalized.question_id === "string") {
    normalized.q_id = normalized.question_id;
  }

  if (!normalized.answer) {
    if (normalized.selected === "OTHER") {
      normalized.answer = String(normalized.other_text ?? "");
    } else if (typeof normalized.selected === "string") {
      normalized.answer = normalized.selected;
    }
  }

  delete normalized.type;
  delete normalized.question_id;

  return normalized;
}
