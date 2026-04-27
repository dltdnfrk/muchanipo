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

export interface PipelineStartedEvent {
  type: "pipeline_started";
  topic: string;
  session_id: string;
  ts: string;
}

export interface InterviewQuestionEvent {
  type: "interview_question";
  question_id: string;
  prompt: string;
  options: { key: "A" | "B" | "C" | "D"; label: string }[];
  allow_other: boolean;
}

export interface CouncilRoundStartEvent {
  type: "council_round_start";
  round: number;
  layer: LayerName;
  personas: string[];
}

export interface CouncilTokenEvent {
  type: "council_token";
  round: number;
  persona: string;
  delta: string;
}

export interface CouncilRoundEndEvent {
  type: "council_round_end";
  round: number;
  layer: LayerName;
  summary: string;
}

export interface ReportChunkEvent {
  type: "report_chunk";
  delta: string;
  done: boolean;
}

export interface PipelineErrorEvent {
  type: "pipeline_error";
  message: string;
  fatal: boolean;
}

export interface PipelineDoneEvent {
  type: "pipeline_done";
  report_path: string;
}

export type BackendEvent =
  | PipelineStartedEvent
  | InterviewQuestionEvent
  | CouncilRoundStartEvent
  | CouncilTokenEvent
  | CouncilRoundEndEvent
  | ReportChunkEvent
  | PipelineErrorEvent
  | PipelineDoneEvent;

export interface UserAction {
  type: "interview_answer" | "cancel" | "resume";
  question_id?: string;
  selected?: "A" | "B" | "C" | "D" | "OTHER";
  other_text?: string;
}
