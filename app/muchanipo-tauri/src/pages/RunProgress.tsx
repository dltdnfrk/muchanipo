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
  council: "심의 (10 round)",
  report: "보고서 작성",
  finalize: "완료",
};

function initialState(): Record<Stage, StageState> {
  const init: Record<Stage, StageState> = {} as any;
  for (const s of STAGES) {
    init[s] = { status: "pending", message: "" };
  }
  return init;
}

export default function RunProgress() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const [stages, setStages] = useState<Record<Stage, StageState>>(() => initialState());
  const [councilRound, setCouncilRound] = useState<number>(0);
  const [topic, setTopic] = useState<string>("");
  const unlistenRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (!runId) return;
    try {
      setTopic(localStorage.getItem(`run:${runId}:topic`) || "");
    } catch {
      /* ignore */
    }
  }, [runId]);

  useEffect(() => {
    let mounted = true;

    onBackendEvent((event: BackendEvent) => {
      if (!mounted) return;

      // stage_started / stage_completed
      if (
        (event.event === "stage_started" || event.event === "stage_completed") &&
        typeof event.stage === "string"
      ) {
        const stage = event.stage as Stage;
        if (!STAGES.includes(stage)) return;

        setStages((prev) => {
          const next = { ...prev };
          const current = { ...next[stage] };
          if (event.event === "stage_started") {
            current.status = "active";
            current.startedAt = Date.now();
            current.message = "진행 중…";
          } else {
            current.status = "completed";
            current.completedAt = Date.now();
            if (current.startedAt) {
              current.durationMs = current.completedAt - current.startedAt;
            }
            current.message = "완료";
          }
          next[stage] = current;
          return next;
        });
        return;
      }

      // council_round_start
      if (event.event === "council_round_start" && typeof event.round === "number") {
        setCouncilRound(event.round);
        return;
      }

      // final_report — capture markdown into localStorage so ReportView can render
      if (event.event === "final_report" && runId) {
        const markdown = (event.markdown as string) || "";
        const reportPath = (event.report_path as string) || "";
        const chapterCount = (event.chapter_count as number) || 0;
        try {
          localStorage.setItem(`run:${runId}:report`, markdown);
          localStorage.setItem(`run:${runId}:report_path`, reportPath);
          localStorage.setItem(`run:${runId}:chapter_count`, String(chapterCount));
        } catch {
          /* ignore */
        }
        return;
      }

      // done — pipeline complete, jump to report view
      if (event.event === "done" && runId) {
        setTimeout(() => {
          if (mounted) navigate(`/report/${runId}`);
        }, 600);
        return;
      }

      if (event.event === "error") {
        setStages((prev) => {
          const next = { ...prev };
          for (const stage of STAGES) {
            if (next[stage].status === "active") {
              next[stage] = {
                ...next[stage],
                status: "error",
                message: (event.message as string) || "오류 발생",
              };
            }
          }
          return next;
        });
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
      if (unlistenRef.current) unlistenRef.current();
    };
  }, [runId, navigate]);

  return (
    <div className="min-h-screen bg-[#15141B] px-4 py-10">
      <div className="mx-auto max-w-3xl">
        <h1 className="mb-2 text-center text-2xl font-bold text-[#E8E0D0]">
          리서치 진행 상황
        </h1>
        {topic && (
          <p className="mb-2 text-center text-sm text-[#FFB347]">"{topic}"</p>
        )}
        <p className="mb-10 text-center text-xs text-[#6E6B7A]">Run ID: {runId}</p>

        <div className="relative space-y-0">
          <div className="absolute left-5 top-4 bottom-4 w-px bg-[#2A2833]" />

          {STAGES.map((stage) => {
            const state = stages[stage];
            const isActive = state.status === "active";
            const isCompleted = state.status === "completed";
            const isError = state.status === "error";

            return (
              <div key={stage} className="relative flex items-start gap-4 py-4">
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
                </div>

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
                      {stage === "council" && isActive && councilRound > 0 && (
                        <span className="ml-2 text-xs text-[#FFB347]">
                          {councilRound}/10
                        </span>
                      )}
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
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
