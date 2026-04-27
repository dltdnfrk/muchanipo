import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { onMuchanipoEvent, type MuchanipoEvent, type MuchanipoStage } from "../lib/tauriClient";

interface StageState {
  status: "pending" | "active" | "completed" | "error";
  message: string;
  startedAt?: number;
  completedAt?: number;
  durationMs?: number;
}

const STAGES: MuchanipoStage[] = [
  "intake",
  "interview",
  "targeting",
  "research",
  "evidence",
  "council",
  "report",
  "finalize",
];

const STAGE_LABELS: Record<MuchanipoStage, string> = {
  intake: "아이디어 접수",
  interview: "인터뷰",
  targeting: "타겟팅",
  research: "리서치",
  evidence: "증거 수집",
  council: "심의",
  report: "보고서 작성",
  finalize: "완료",
};

export default function RunProgress() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const [stages, setStages] = useState<Record<MuchanipoStage, StageState>>(() => {
    const init: Record<MuchanipoStage, StageState> = {} as any;
    for (const s of STAGES) {
      init[s] = { status: "pending", message: "" };
    }
    return init;
  });
  const unlistenRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    let mounted = true;

    onMuchanipoEvent((event: MuchanipoEvent) => {
      if (!mounted) return;

      setStages((prev) => {
        const next = { ...prev };
        const current = { ...next[event.stage] };

        if (event.type === "started") {
          current.status = "active";
          current.startedAt = Date.now();
          current.message = (event.payload.message as string) || "진행 중…";
        } else if (event.type === "progress") {
          current.status = "active";
          current.message = (event.payload.message as string) || current.message;
        } else if (event.type === "completed") {
          current.status = "completed";
          current.completedAt = Date.now();
          if (current.startedAt) {
            current.durationMs = current.completedAt - current.startedAt;
          }
          current.message = (event.payload.message as string) || "완료";
        } else if (event.type === "error") {
          current.status = "error";
          current.message = (event.payload.message as string) || "오류 발생";
        }

        next[event.stage] = current;
        return next;
      });

      if (event.type === "completed" && event.stage === "finalize") {
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

  return (
    <div className="min-h-screen bg-[#15141B] px-4 py-10">
      <div className="mx-auto max-w-3xl">
        <h1 className="mb-8 text-center text-2xl font-bold text-[#E8E0D0]">
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
                <div className="relative z-10 flex h-10 w-10 shrink-0 items-center justify-center rounded-full border-2">
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
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
