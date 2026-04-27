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

export async function submitIdea(idea: string): Promise<{ run_id: string }> {
  return invoke("submit_idea", { idea });
}

export async function fetchReport(runId: string): Promise<FinalReport> {
  return invoke("fetch_report", { runId });
}

export async function onMuchanipoEvent(
  handler: (e: MuchanipoEvent) => void,
): Promise<UnlistenFn> {
  return listen<MuchanipoEvent>("muchanipo_event", ({ payload }) => {
    handler(payload);
  });
}
