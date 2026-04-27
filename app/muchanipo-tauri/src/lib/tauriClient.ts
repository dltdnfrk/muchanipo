import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

export type MuchanipoStage =
  | "intake"
  | "interview"
  | "targeting"
  | "research"
  | "evidence"
  | "council"
  | "report"
  | "finalize";

export type MuchanipoEventType = "started" | "progress" | "completed" | "error";

export interface MuchanipoEvent {
  stage: MuchanipoStage;
  type: MuchanipoEventType;
  payload: Record<string, unknown>;
  timestamp: string;
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
}

export interface FinalReport {
  brief_id: string;
  title: string;
  chapters: Chapter[];
}

export async function submitIdea(
  idea: string,
  pipeline: "stub" | "full" = "full",
): Promise<{ run_id: string }> {
  return invoke("start_pipeline", { topic: idea, pipeline });
}

export async function fetchReport(runId: string): Promise<FinalReport> {
  return invoke("fetch_report", { runId });
}

export async function onMuchanipoEvent(
  handler: (e: MuchanipoEvent) => void,
): Promise<UnlistenFn> {
  return listen<Record<string, unknown>>("backend_event", ({ payload }) => {
    const adapted: MuchanipoEvent = {
      stage: (payload.stage as MuchanipoStage) || "intake",
      type: (payload.type as MuchanipoEventType) || "progress",
      payload: (payload.payload as Record<string, unknown>) || {},
      timestamp: (payload.timestamp as string) || new Date().toISOString(),
    };
    handler(adapted);
  });
}
