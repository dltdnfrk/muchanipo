import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getBufferedEvents, onBackendEvent, submitIdea, type BackendEvent, type PipelineMode } from "../lib/tauriClient";
import { markRunDone } from "../lib/runsIndex";

function readEnvsFromSettings(): Record<string, string> {
  const backendMode =
    (localStorage.getItem("backend_mode") as "cli" | "api" | null) || "cli";
  const envs: Record<string, string> = {};
  if (backendMode === "cli") {
    envs.MUCHANIPO_USE_CLI = "1";
  } else {
    const carry = (k: string, e: string) => {
      const v = localStorage.getItem(k);
      if (v) envs[e] = v;
    };
    carry("anthropic_api_key", "ANTHROPIC_API_KEY");
    carry("gemini_api_key", "GEMINI_API_KEY");
    carry("kimi_api_key", "KIMI_API_KEY");
    carry("openai_api_key", "OPENAI_API_KEY");
    carry("openalex_email", "OPENALEX_EMAIL");
    carry("plannotator_key", "PLANNOTATOR_API_KEY");
  }
  return envs;
}

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
  layer?: string;
  round?: number;
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

const STAGE_LABEL: Record<Stage, string> = {
  intake: "아이디어 접수",
  interview: "인터뷰",
  targeting: "타겟팅",
  research: "리서치",
  evidence: "증거 수집",
  council: "심의",
  report: "보고서",
  finalize: "완료",
};

function initialState(): Record<Stage, StageState> {
  const init: Record<Stage, StageState> = {} as Record<Stage, StageState>;
  for (const s of STAGES) init[s] = { status: "pending", message: "" };
  return init;
}

export default function RunProgress() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const [stages, setStages] = useState<Record<Stage, StageState>>(() => initialState());
  const [councilRound, setCouncilRound] = useState<number>(0);
  const [topic, setTopic] = useState<string>("");
  const [tokenCards, setTokenCards] = useState<TokenCard[]>([]);
  const [runError, setRunError] = useState<string | null>(null);
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
    const handleEvent = (event: BackendEvent) => {
      if (!mounted) return;

      if (event.event === "error") {
        setRunError((event.message as string) || "오류가 발생했어요.");
        return;
      }

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
            current.message = "진행 중";
          } else {
            current.status = "completed";
            current.completedAt = Date.now();
            if (current.startedAt) current.durationMs = current.completedAt - current.startedAt;
            current.message = "완료";
          }
          next[stage] = current;
          return next;
        });
        return;
      }

      if (event.event === "council_round_start" && typeof event.round === "number") {
        setCouncilRound(event.round);
        return;
      }

      if (event.event === "council_persona_token") {
        const persona = String(event.persona ?? "agent");
        const layer = event.layer as string | undefined;
        const round = event.round as number | undefined;
        const delta = String(event.delta ?? "");
        setTokenCards((prev) => {
          const last = prev[prev.length - 1];
          if (last && last.persona === persona && last.layer === layer && last.round === round) {
            return [...prev.slice(0, -1), { ...last, text: last.text + delta }];
          }
          return [...prev, { persona, text: delta, layer, round }].slice(-12);
        });
        return;
      }

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

      if (event.event === "done" && runId && !runError) {
        markRunDone(runId);
        setTimeout(() => {
          if (mounted) navigate(`/report/${runId}`);
        }, 600);
        return;
      }
    };

    onBackendEvent(handleEvent).then(async (unlisten) => {
      if (!mounted) {
        unlisten();
        return;
      }
      unlistenRef.current = unlisten;

      // Replay any events the active pipeline already emitted before this
      // listener was attached (e.g. user navigated to another page and came
      // back via the sidebar). Without replay the stage list stays at 0/8
      // even though Python is mid-run.
      try {
        const history = await getBufferedEvents();
        for (const e of history) handleEvent(e);
      } catch {
        /* non-fatal */
      }

      // Listener + replay done — now safe to start the pipeline if this
      // mount owns the run kick-off (pending flag is set by IdeaSubmit).
      if (!runId) return;
      try {
        const pending = localStorage.getItem(`run:${runId}:pending`);
        if (pending !== "1") return;
        localStorage.removeItem(`run:${runId}:pending`);
        const topic = localStorage.getItem(`run:${runId}:topic`) || "";
        if (!topic) {
          setRunError("주제 정보가 없습니다.");
          return;
        }
        const pipelineMode =
          (localStorage.getItem("pipeline_mode") as PipelineMode | null) || "full";
        const envs = readEnvsFromSettings();
        await submitIdea(topic, pipelineMode, envs);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setRunError(msg);
      }
    });

    return () => {
      mounted = false;
      if (unlistenRef.current) unlistenRef.current();
    };
  }, [runId, navigate, runError]);

  const completedCount = STAGES.filter((s) => stages[s].status === "completed").length;
  const totalProgress = (completedCount / STAGES.length) * 100;

  return (
    <div className="min-h-screen px-6 py-10">
      <div className="mx-auto max-w-3xl">
        {/* Header */}
        <div className="fade-in mb-8">
          <h1 className="text-xl font-semibold tracking-tight text-white">
            {topic || "(주제 없음)"}
          </h1>
          <p className="mt-1 text-xs text-tertiary">{runId}</p>
        </div>

        {/* Progress meter */}
        <div className="fade-in mb-6 flex items-center gap-3">
          <div className="h-1 flex-1 overflow-hidden rounded-full bg-white/10">
            <div
              className="h-full rounded-full bg-white transition-all duration-500"
              style={{ width: `${totalProgress}%` }}
            />
          </div>
          <span className="font-mono text-xs text-secondary">
            {completedCount}/{STAGES.length}
          </span>
        </div>

        {/* Run error banner */}
        {runError && (
          <div className="fade-in mb-6 flex items-start justify-between gap-4 rounded-xl border border-red-500/20 bg-red-500/5 px-4 py-3">
            <p className="break-all text-sm text-red-300">{runError}</p>
            <button
              onClick={() => navigate("/")}
              className="shrink-0 rounded-full border border-white/10 px-3 py-1 text-xs text-secondary transition hover:bg-white/5 hover:text-white"
            >
              처음으로
            </button>
          </div>
        )}

        {/* Stage list (vertical, ChatGPT-style minimalist) */}
        <ul className="space-y-px overflow-hidden rounded-xl border border-white/5">
          {STAGES.map((stage) => {
            const state = stages[stage];
            const isActive = state.status === "active";
            const isCompleted = state.status === "completed";
            const isError = state.status === "error";

            return (
              <li
                key={stage}
                className={`flex items-center gap-3 px-4 py-3 transition ${
                  isActive ? "bg-white/5" : "bg-white/[0.02]"
                }`}
              >
                <div className="flex h-5 w-5 shrink-0 items-center justify-center">
                  {isCompleted ? (
                    <svg className="h-4 w-4 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                    </svg>
                  ) : isError ? (
                    <svg className="h-4 w-4 text-red-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  ) : isActive ? (
                    <svg className="h-3.5 w-3.5 animate-spin text-white" viewBox="0 0 24 24" fill="none">
                      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.3" strokeWidth="3" />
                      <path d="M12 2a10 10 0 0110 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
                    </svg>
                  ) : (
                    <div className="h-1.5 w-1.5 rounded-full bg-white/20" />
                  )}
                </div>

                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline justify-between gap-3">
                    <span className={`text-sm ${
                      isActive
                        ? "text-white"
                        : isCompleted
                        ? "text-secondary"
                        : isError
                        ? "text-red-300"
                        : "text-tertiary"
                    }`}>
                      {STAGE_LABEL[stage]}
                    </span>
                    <span className="shrink-0 font-mono text-[10px] text-tertiary">
                      {state.durationMs ? `${Math.round(state.durationMs / 1000)}s` : ""}
                    </span>
                  </div>
                  {stage === "council" && isActive && councilRound > 0 && (
                    <p className="mt-0.5 text-[11px] text-tertiary">
                      Round <span className="font-mono text-white">{councilRound}</span> / 10
                    </p>
                  )}
                </div>
              </li>
            );
          })}
        </ul>

        {/* Streaming token cards (minimal monochrome) */}
        {tokenCards.length > 0 && (
          <div className="fade-in mt-8">
            <p className="mb-3 text-[11px] uppercase tracking-wider text-tertiary">
              Council activity
            </p>
            <div className="space-y-px overflow-hidden rounded-xl border border-white/5">
              {tokenCards.map((card, idx) => (
                <div
                  key={idx}
                  className="bg-white/[0.02] px-4 py-3"
                >
                  <div className="mb-1 flex items-center gap-2 text-[10px] text-tertiary">
                    <span className="font-mono text-white">{card.persona}</span>
                    {card.layer && <span>·</span>}
                    {card.layer && <span>{card.layer}</span>}
                    {card.round !== undefined && <span>·</span>}
                    {card.round !== undefined && <span>R{card.round}</span>}
                  </div>
                  <p className="break-words text-xs leading-relaxed text-secondary">{card.text}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
