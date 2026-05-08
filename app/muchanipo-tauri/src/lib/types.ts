export type LayerName =
  | "intent"
  | "research"
  | "evidence"
  | "council"
  | "synthesis"
  | "critique"
  | "refine"
  | "verify"
  | "report"
  | "publish";

export type BackendEventKind =
  | "pipeline_started"
  | "run_started"
  | "deep_interview_progress"
  | "deep_interview_artifacts"
  | "interview_ontology_delta"
  | "interview_question"
  | "research_progress"
  | "council_round_start"
  | "council_token"
  | "council_turn"
  | "council_persona_token"
  | "council_round_end"
  | "council_round_done"
  | "report_chunk"
  | "final_report"
  | "pipeline_error"
  | "error"
  | "pipeline_done"
  | "done";

interface BackendEventEnvelope {
  event?: BackendEventKind | string;
  type?: BackendEventKind | string;
  [key: string]: unknown;
}

export interface PipelineStartedEvent extends BackendEventEnvelope {
  type: "pipeline_started";
  event?: "pipeline_started" | "run_started";
  topic: string;
  session_id: string;
  ts: string;
}

export interface InterviewQuestionEvent extends BackendEventEnvelope {
  type: "interview_question";
  event?: "interview_question";
  question_id: string;
  prompt: string;
  options: { key: string; label: string }[];
  allow_other: boolean;
}

export interface InterviewOntologyDeltaEvent extends BackendEventEnvelope {
  type: "interview_ontology_delta";
  event?: "interview_ontology_delta";
  q_id?: string;
  question_id?: string;
  ontology_state?: Record<string, unknown>;
  ontology_delta?: Record<string, unknown>;
  entities?: Record<string, unknown>[];
  relations?: Record<string, unknown>[];
  unknowns?: Record<string, unknown>[];
  targets_unknown_ids?: string[];
  question_quality_gate?: Record<string, unknown>;
  coverage?: number;
  open_unknown_count?: number;
}

export interface CouncilRoundStartEvent extends BackendEventEnvelope {
  type: "council_round_start";
  event?: "council_round_start";
  round: number;
  layer: LayerName;
  personas: string[];
}

export interface CouncilTokenEvent extends BackendEventEnvelope {
  type: "council_token";
  event?: "council_token" | "council_turn" | "council_persona_token";
  round: number;
  persona: string;
  delta: string;
}

export interface CouncilRoundEndEvent extends BackendEventEnvelope {
  type: "council_round_end";
  event?: "council_round_end" | "council_round_done";
  round: number;
  layer: LayerName;
  summary: string;
}

export interface ReportChunkEvent extends BackendEventEnvelope {
  type: "report_chunk";
  event?: "report_chunk";
  delta: string;
  done: boolean;
}

export interface ResearchProgressEvent extends BackendEventEnvelope {
  type: "research_progress";
  event?: "research_progress";
  status: string;
  query?: string;
  query_index?: number;
  query_count?: number;
  backends?: string[];
  source_title?: string;
  source_url?: string;
  source_grade?: string;
  source_kind?: string;
  access_status?: string;
  accepted?: boolean;
  facet_ids?: string[];
  relevance_score?: number;
  reason?: string;
  facet_id?: string;
  message?: string;
  accepted_count?: number;
  min_accepted_sources?: number;
  gap_count?: number;
}

export interface PipelineErrorEvent extends BackendEventEnvelope {
  type: "pipeline_error";
  event?: "pipeline_error" | "error";
  message: string;
  fatal: boolean;
}

export interface PipelineDoneEvent extends BackendEventEnvelope {
  type: "pipeline_done";
  event?: "pipeline_done" | "done";
  report_path: string;
}

export type BackendEvent =
  | PipelineStartedEvent
  | InterviewOntologyDeltaEvent
  | InterviewQuestionEvent
  | ResearchProgressEvent
  | CouncilRoundStartEvent
  | CouncilTokenEvent
  | CouncilRoundEndEvent
  | ReportChunkEvent
  | PipelineErrorEvent
  | PipelineDoneEvent;

export interface UserAction {
  type: "interview_answer" | "cancel" | "resume";
  question_id?: string;
  selected?: string;
  other_text?: string;
}

export function backendEventName(event: BackendEvent): string {
  return String(event.event ?? event.type ?? "");
}
