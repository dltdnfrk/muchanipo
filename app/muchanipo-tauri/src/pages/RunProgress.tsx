import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  onBackendEvent,
  type BackendEvent,
} from "../lib/tauriClient";

type Stage =
  | "intake"
  | "interview"
  | "targeting"
  | "research"
  | "evidence"
  | "council"
  | "report"
  | "finalize";

interface StageState {
  status: "pending" | "active" | "completed" | "error";
  message: string;
  startedAt?: number;
  completedAt?: number;
  durationMs?: number;
}

interface TokenCard {
  persona: string;
  text: string;
}

const STAGES: Stage[] = [
  "intake",
  "interview",
  "targeting",
  "research",
  "evidence",
  "council",
  "report",
  "finalize",
];

const STAGE_LABELS: Record<Stage, string> = {
  intake: "아이디어 접수",
  interview: "인터뷰",
  targeting: "타겟팅",
  research: "리서치",
  evidence: "증거 수집",
  council: "심의",
  report: "보고서 작성",
  finalize: "완료",
};

function stageFromEvent(event: string): Stage | null {
  if (event === "error") return null;
  const map: Record<string, Stage> = {
    pipeline_started: "intake",
    interview_question: "interview",
    targeting_complete: "targeting",
    research_complete: "research",
    evidence_complete: "evidence",
    council_round_start: "council",
    council_token: "council",
    council_round_end: "council",
    report_chunk: "report",
    report_complete: "report",
    pipeline_done: "finalize",
  };
  return map[event] ?? null;
}

export default function RunProgress() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const [stages, setStages] = useState<Record<Stage, StageState>>(() => {
    const init: Record<Stage, StageState> = {} as any;
    for (const s of STAGES) {
      init[s] = { status: "pending", message: "" };
    }
    return init;
  });
  const [tokenCards, setTokenCards] = useState<TokenCard[]>([]);
  const unlistenRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    let mounted = true;

    onBackendEvent((event: BackendEvent) => {
      if (!mounted) return;

      if (event.event === "error") {
        setStages((prev) => {
          const next = { ...prev };
          const activeStages = STAGES.filter((s) => prev[s].status === "active");
          const targets = activeStages.length > 0 ? activeStages : (["finalize"] as Stage[]);
          const now = Date.now();

          for (const target of targets) {
            next[target] = {
              ...next[target],
              status: "error",
              completedAt: now,
              durationMs: next[target].startedAt ? now - next[target].startedAt : undefined,
              message: String(event.message || "오류"),
            };
          }

          return next;
        });
        return;
      }

      const stage = stageFromEvent(event.event);
      if (stage) {
        setStages((prev) => {
          const next = { ...prev };
          const current = { ...next[stage] };

          if (event.event === "pipeline_started") {
            current.status = "active";
            current.startedAt = Date.now();
            current.message = "시작됨";
          } else if (event.event === "pipeline_done") {
            current.status = "completed";
            current.completedAt = Date.now();
            if (current.startedAt) {
              current.durationMs = current.completedAt - current.startedAt;
            }
            current.message = "완료";
          } else if (current.status !== "completed") {
            current.status = "active";
            if (current.startedAt == null) {
              current.startedAt = Date.now();
            }
            current.message = event.message || String(event.event);
          }

          next[stage] = current;
          return next;
        });
      }

      // council persona token streaming
      if (event.event === "council_persona_token") {
        const persona = String(event.persona || "Unknown");
        const delta = String(event.delta || "");
        setTokenCards((prev) => {
          const existing = prev.find((c) => c.persona === persona);
          if (existing) {
            return prev.map((c) =>
              c.persona === persona ? { ...c, text: c.text + delta } : c
            );
          }
          return [...prev, { persona, text: delta }];
        });
      }

      if (event.event === "pipeline_done") {
        // store report metadata for ReportView
        try {
          if (event.report_path) {
            localStorage.setItem(`run:${runId}:report_path`, String(event.report_path));
          }
          if (event.chapter_count != null) {
            localStorage.setItem(`run:${runId}:chapter_count`, String(event.chapter_count));
          }
          if (event.markdown) {
            localStorage.setItem(`run:${runId}:report`, String(event.markdown));
          }
        } catch {
          /* ignore */
        }
        setTimeout(() => {
          if (mounted && runId) {
            navigate(`/report/${runId}`);
          }
        }, 800);
      }
    }).then((unlisten) => {
      if (mounted) {
        unlistenRef.current = unlisten;
      } else {
        unlisten();
      }
    });

    return () => {
      mounted = false;
      if (unlistenRef.current) {
        unlistenRef.current();
      }
    };
  }, [runId, navigate]);

  const councilActive = stages.council.status === "active";

  return (
    <div className="min-h-screen bg-[#15141B] px-4 py-10">
      <div className="mx-auto max-w-3xl">
        <h1 className="mb-2 text-center text-2xl font-bold text-[#E8E0D0]">
          리서치 진행 상황
        </h1>
        <p className="mb-10 text-center text-sm text-[#8A8599]">
          Run ID: {runId}
        </p>

        <div className="relative space-y-0">
          {/* vertical line */}
          <div className="absolute left-5 top-4 bottom-4 w-px bg-[#2A2833]" />

          {STAGES.map((stage) => {
            const state = stages[stage];
            const isActive = state.status === "active";
            const isCompleted = state.status === "completed";
            const isError = state.status === "error";

            return (
              <div key={stage} className="relative flex items-start gap-4 py-4">
                {/* indicator dot */}
                <div className="relative z-10 flex h-10 w-10 shrink-0 items-center justify-center rounded-full border-2 border-[#2A2833] bg-[#15141B]">
                  {isCompleted ? (
                    <svg className="h-5 w-5 text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                    </svg>
                  ) : isError ? (
                    <svg className="h-5 w-5 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  ) : isActive ? (
                    <div className="h-4 w-4 animate-spin rounded-full border-2 border-[#FFB347] border-t-transparent" />
                  ) : (
                    <div className="h-2 w-2 rounded-full bg-[#5A5669]" />
                  )}
                  <span className="sr-only">{state.status}</span>
                </div>

                {/* content */}
                <div className="flex-1 pt-1">
                  <div className="flex items-center justify-between">
                    <h3
                      className={`text-sm font-semibold ${
                        isActive
                          ? "text-[#FFB347]"
                          : isCompleted
                          ? "text-[#E8E0D0]"
                          : isError
                          ? "text-red-400"
                          : "text-[#5A5669]"
                      }`}
                    >
                      {STAGE_LABELS[stage]}
                    </h3>
                    {state.durationMs && (
                      <span className="text-xs text-[#6E6B7A]">
                        {Math.round(state.durationMs / 1000)}s
                      </span>
                    )}
                  </div>
                  {state.message && (
                    <p className="mt-1 text-xs text-[#8A8599]">{state.message}</p>
                  )}

                  {/* Streaming token cards for council */}
                  {stage === "council" && councilActive && tokenCards.length > 0 && (
                    <div className="mt-3 space-y-2">
                      {tokenCards.map((card) => (
                        <div
                          key={card.persona}
                          className="rounded-lg border-l-4 border-[#FFB347] bg-[#1E1D26] p-3"
                        >
                          <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-[#FFB347]">
                            {card.persona}
                          </div>
                          <p className="whitespace-pre-wrap text-xs leading-relaxed text-[#C8C0B0]">
                            {card.text}
                          </p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
