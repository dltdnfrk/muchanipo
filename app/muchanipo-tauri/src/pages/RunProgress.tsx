import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  getBufferedEvents,
  onBackendEvent,
  sendAction,
  submitIdea,
  type BackendEvent,
  type PipelineMode,
  type ResearchDepth,
} from "../lib/tauriClient";
import { deleteRun, listRuns, markRunDone, markRunRunning } from "../lib/runsIndex";

type BackendMode = "offline" | "cli" | "api";

function readBackendMode(): BackendMode {
  const value = localStorage.getItem("backend_mode");
  return value === "cli" || value === "api" || value === "offline" ? value : "cli";
}

function readEnvsFromSettings(): Record<string, string> {
  const backendMode = readBackendMode();
  const envs: Record<string, string> = {};
  if (backendMode === "offline") {
    envs.MUCHANIPO_OFFLINE = "1";
  } else if (backendMode === "cli") {
    envs.MUCHANIPO_USE_CLI = "1";
    envs.MUCHANIPO_ONLINE = "1";
    envs.MUCHANIPO_REQUIRE_LIVE = "1";
  } else {
    envs.MUCHANIPO_ONLINE = "1";
    envs.MUCHANIPO_REQUIRE_LIVE = "1";
    const carry = (k: string, e: string) => {
      const v = localStorage.getItem(k);
      if (v) envs[e] = v;
    };
    carry("anthropic_api_key", "ANTHROPIC_API_KEY");
    carry("gemini_api_key", "GEMINI_API_KEY");
    carry("kimi_api_key", "KIMI_API_KEY");
    carry("openai_api_key", "OPENAI_API_KEY");
    carry("opencode_api_key", "OPENCODE_API_KEY");
    carry("openalex_email", "OPENALEX_EMAIL");
    carry("plannotator_key", "PLANNOTATOR_API_KEY");
  }
  return envs;
}

function readResearchDepth(): ResearchDepth {
  const value = localStorage.getItem("research_depth");
  return value === "shallow" || value === "deep" || value === "max" ? value : "deep";
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

interface InterviewPrompt {
  id: string;
  header: string;
  text: string;
  options: { key: string; label: string; value: string; description?: string }[];
  allowOther: boolean;
  multiSelect: boolean;
  preview?: string;
  index?: number;
  total?: number;
}

interface HitlPrompt {
  gate: string;
  title: string;
  prompt: string;
  preview?: string;
  options: { key: string; label: string; value: string; description?: string }[];
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

const PHASE_TO_STAGE: Record<string, Stage> = {
  STARTUP: "intake",
  INTERVIEW: "interview",
  COUNCIL: "council",
  REPORT: "report",
};

function initialState(): Record<Stage, StageState> {
  const init: Record<Stage, StageState> = {} as Record<Stage, StageState>;
  for (const s of STAGES) init[s] = { status: "pending", message: "" };
  return init;
}

function normalizeInterviewPrompt(event: BackendEvent): InterviewPrompt | null {
  const data =
    event.data && typeof event.data === "object"
      ? (event.data as Record<string, unknown>)
      : {};
  const id = String(event.q_id ?? event.question_id ?? data.q_id ?? data.question_id ?? "Q1");
  const text = String(event.text ?? event.prompt ?? data.text ?? data.prompt ?? "").trim();
  if (!text) return null;
  const header = String(event.header ?? data.header ?? "Interview input required");
  const preview = String(event.preview ?? data.preview ?? "").trim();
  const index = Number(event.index ?? data.index ?? 0) || undefined;
  const total = Number(event.total ?? data.total ?? 0) || undefined;

  const rawOptions = Array.isArray(event.options)
    ? event.options
    : Array.isArray(data.options)
    ? data.options
    : [];
  const options = rawOptions.map((raw, idx) => {
    if (raw && typeof raw === "object") {
      const item = raw as Record<string, unknown>;
      const key = String(item.key ?? String.fromCharCode(65 + idx));
      const label = String(item.label ?? item.text ?? item.value ?? key);
      const description = String(item.description ?? "").trim();
      return { key, label, value: String(item.value ?? label), description };
    }
    const value = String(raw);
    const match = value.match(/^([A-D])[\).\s-]+(.+)$/i);
    if (match) {
      return { key: match[1].toUpperCase(), label: match[2], value };
    }
    const key = String.fromCharCode(65 + idx);
    return { key, label: value, value };
  });

  return {
    id,
    header,
    text,
    options,
    allowOther: event.allow_other !== false && data.allow_other !== false,
    multiSelect:
      event.multiSelect === true ||
      event.multi_select === true ||
      data.multiSelect === true ||
      data.multi_select === true,
    preview: preview || undefined,
    index,
    total,
  };
}

function normalizeHitlPrompt(event: BackendEvent): HitlPrompt | null {
  const data =
    event.data && typeof event.data === "object"
      ? (event.data as Record<string, unknown>)
      : {};
  const gate = String(event.gate ?? data.gate ?? "").trim();
  if (!gate) return null;
  const title = String(event.title ?? data.title ?? `${gate} 승인`);
  const prompt = String(event.prompt ?? data.prompt ?? "계속 진행하려면 승인하세요.");
  const preview = String(event.preview ?? data.preview ?? "").trim();
  const rawOptions = Array.isArray(event.options)
    ? event.options
    : Array.isArray(data.options)
    ? data.options
    : [];
  const options = rawOptions.map((raw, idx) => {
    if (raw && typeof raw === "object") {
      const item = raw as Record<string, unknown>;
      const key = String(item.key ?? String.fromCharCode(65 + idx));
      const label = String(item.label ?? item.text ?? item.value ?? key);
      const description = String(item.description ?? "").trim();
      return { key, label, value: String(item.value ?? label), description };
    }
    const value = String(raw);
    const key = String.fromCharCode(65 + idx);
    return { key, label: value, value };
  });
  return {
    gate,
    title,
    prompt,
    preview: preview || undefined,
    options:
      options.length > 0
        ? options
        : [
            {
              key: "approve",
              label: "승인하고 계속",
              value: "approved",
              description: "현재 내용을 승인하고 다음 단계로 진행합니다.",
            },
          ],
  };
}

export default function RunProgress() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const [stages, setStages] = useState<Record<Stage, StageState>>(() => initialState());
  const [councilRound, setCouncilRound] = useState<number>(0);
  const [topic, setTopic] = useState<string>("");
  const [tokenCards, setTokenCards] = useState<TokenCard[]>([]);
  const [runError, setRunError] = useState<string | null>(null);
  const runErrorRef = useRef<string | null>(null);
  const [runWarnings, setRunWarnings] = useState<string[]>([]);
  const [reportPreview, setReportPreview] = useState("");
  const [interviewPrompt, setInterviewPrompt] = useState<InterviewPrompt | null>(null);
  const [interviewAnswer, setInterviewAnswer] = useState("");
  const [interviewSelections, setInterviewSelections] = useState<string[]>([]);
  const [interviewSubmitting, setInterviewSubmitting] = useState(false);
  const [interviewError, setInterviewError] = useState<string | null>(null);
  const [hitlPrompt, setHitlPrompt] = useState<HitlPrompt | null>(null);
  const [hitlSubmitting, setHitlSubmitting] = useState(false);
  const [hitlError, setHitlError] = useState<string | null>(null);
  const [aborting, setAborting] = useState(false);
  const unlistenRef = useRef<(() => void) | null>(null);
  const chunkKeysRef = useRef<Set<string>>(new Set());
  const finalReportReceivedRef = useRef(false);
  const autoRecoveredRunsRef = useRef<Set<string>>(new Set());

  const startRunFromTopic = useCallback(
    async (runTopic: string, options: { clearArtifacts?: boolean; warning?: string } = {}) => {
      if (!runId) return false;
      const trimmed = runTopic.trim();
      if (!trimmed) {
        runErrorRef.current = "주제 정보가 없습니다.";
        setRunError("주제 정보가 없습니다.");
        return false;
      }

      runErrorRef.current = null;
      setRunError(null);
      setRunWarnings(options.warning ? [options.warning] : []);
      setTopic(trimmed);

      if (options.clearArtifacts) {
        chunkKeysRef.current.clear();
        finalReportReceivedRef.current = false;
        setStages(initialState());
        setCouncilRound(0);
        setTokenCards([]);
        setReportPreview("");
        setInterviewPrompt(null);
        setInterviewAnswer("");
        setInterviewSelections([]);
        setInterviewError(null);
        setHitlPrompt(null);
        setHitlError(null);
        setHitlSubmitting(false);
        try {
          for (const suffix of ["report", "report_path", "chapter_count", "pending"]) {
            localStorage.removeItem(`run:${runId}:${suffix}`);
          }
          markRunRunning(runId);
        } catch {
          /* ignore */
        }
      }

      try {
        const pipelineMode =
          (localStorage.getItem("pipeline_mode") as PipelineMode | null) || "full";
        await submitIdea(trimmed, pipelineMode, readResearchDepth(), readEnvsFromSettings());
        return true;
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        runErrorRef.current = msg;
        setRunError(msg);
        return false;
      }
    },
    [runId],
  );

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
    chunkKeysRef.current.clear();
    finalReportReceivedRef.current = false;
    const handleEvent = (event: BackendEvent) => {
      if (!mounted) return;

      if (event.event === "error") {
        const message = (event.message as string) || "오류가 발생했어요.";
        const isGenericExit = message.startsWith("python pipeline exited with");
        if (isGenericExit && runErrorRef.current) {
          setRunWarnings((prev) =>
            [message, ...prev.filter((item) => item !== message)].slice(0, 3),
          );
        } else {
          runErrorRef.current = message;
          setRunError(message);
        }
        setInterviewSubmitting(false);
        setHitlSubmitting(false);
        setStages((prev) => {
          const next = { ...prev };
          const active = STAGES.find((stage) => next[stage].status === "active");
          if (active) {
            next[active] = {
              ...next[active],
              status: "error",
              completedAt: Date.now(),
              message,
            };
          }
          return next;
        });
        return;
      }

      if (event.event === "warning") {
        const message = (event.message as string) || "경고가 발생했어요.";
        setRunWarnings((prev) => [message, ...prev.filter((item) => item !== message)].slice(0, 3));
        return;
      }

      if (event.event === "interview_question") {
        const prompt = normalizeInterviewPrompt(event);
        if (prompt) {
          setInterviewPrompt(prompt);
          setInterviewAnswer("");
          setInterviewSelections([]);
          setInterviewError(null);
          setInterviewSubmitting(false);
        }
        return;
      }

      if (event.event === "hitl_gate") {
        const prompt = normalizeHitlPrompt(event);
        if (prompt) {
          setHitlPrompt(prompt);
          setHitlError(null);
          setHitlSubmitting(false);
        }
        return;
      }

      if (event.event === "phase_change" && typeof event.phase === "string") {
        const stage = PHASE_TO_STAGE[event.phase.toUpperCase()];
        if (!stage) return;
        if (stage !== "interview") {
          setInterviewPrompt(null);
          setInterviewSubmitting(false);
        }
        setHitlPrompt(null);
        setHitlSubmitting(false);
        setStages((prev) => {
          const next = { ...prev };
          const currentIndex = STAGES.indexOf(stage);
          STAGES.forEach((candidate, idx) => {
            if (idx < currentIndex && next[candidate].status !== "completed") {
              next[candidate] = {
                ...next[candidate],
                status: "completed",
                completedAt: Date.now(),
                message: "완료",
              };
            }
          });
          next[stage] = {
            ...next[stage],
            status: "active",
            startedAt: next[stage].startedAt ?? Date.now(),
            message: "진행 중",
          };
          return next;
        });
        return;
      }

      if (
        (event.event === "stage_started" || event.event === "stage_completed") &&
        typeof event.stage === "string"
      ) {
        const stage = event.stage as Stage;
        if (!STAGES.includes(stage)) return;
        if (event.event === "stage_started" && stage !== "interview") {
          setInterviewPrompt(null);
          setInterviewSubmitting(false);
        }
        if (event.event === "stage_started") {
          setHitlPrompt(null);
          setHitlSubmitting(false);
        }
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

      if (event.event === "report_chunk" && runId) {
        const chunk = String(event.markdown ?? event.delta ?? "");
        const key = chunk.trim();
        if (!key || finalReportReceivedRef.current || chunkKeysRef.current.has(key)) return;
        chunkKeysRef.current.add(key);
        setReportPreview((prev) => {
          const next = `${prev}${prev ? "\n\n" : ""}${chunk}`;
          try {
            localStorage.setItem(`run:${runId}:report`, next);
          } catch {
            /* ignore */
          }
          return next;
        });
        return;
      }

      if (event.event === "final_report" && runId) {
        const markdown = (event.markdown as string) || "";
        const reportPath = (event.report_path as string) || "";
        const vaultPath = (event.vault_path as string) || "";
        const chapterCount = (event.chapter_count as number) || 0;
        finalReportReceivedRef.current = true;
        chunkKeysRef.current.clear();
        try {
          if (markdown) localStorage.setItem(`run:${runId}:report`, markdown);
          localStorage.setItem(`run:${runId}:report_path`, reportPath);
          if (vaultPath) localStorage.setItem(`run:${runId}:vault_path`, vaultPath);
          localStorage.setItem(`run:${runId}:chapter_count`, String(chapterCount));
        } catch {
          /* ignore */
        }
        if (markdown) setReportPreview(markdown);
        return;
      }

      if (event.event === "done" && runId && !runErrorRef.current) {
        setInterviewSubmitting(false);
        setInterviewPrompt(null);
        setHitlSubmitting(false);
        setHitlPrompt(null);
        setStages((prev) => {
          const next = { ...prev };
          for (const stage of STAGES) {
            if (next[stage].status === "active" || stage === "finalize") {
              next[stage] = {
                ...next[stage],
                status: "completed",
                completedAt: Date.now(),
                message: "완료",
              };
            }
          }
          return next;
        });
        if (event.aborted) {
          deleteRun(runId);
          setTimeout(() => {
            if (mounted) navigate("/");
          }, 300);
          return;
        }
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
      let replayedEventCount = 0;
      try {
        const history = await getBufferedEvents();
        replayedEventCount = history.length;
        for (const e of history) handleEvent(e);
      } catch {
        /* non-fatal */
      }

      // Listener + replay done — now safe to start the pipeline if this
      // mount owns the run kick-off (pending flag is set by IdeaSubmit).
      if (!runId) return;
      try {
        const pending = localStorage.getItem(`run:${runId}:pending`);
        const topic = localStorage.getItem(`run:${runId}:topic`) || "";
        if (pending === "1") {
          localStorage.removeItem(`run:${runId}:pending`);
          await startRunFromTopic(topic);
          return;
        }

        const report = localStorage.getItem(`run:${runId}:report`);
        const isRunningEntry = listRuns().some(
          (entry) => entry.runId === runId && entry.status === "running",
        );
        const shouldRecoverStaleRun =
          replayedEventCount === 0 &&
          !report &&
          isRunningEntry &&
          topic.trim() &&
          !autoRecoveredRunsRef.current.has(runId);

        if (shouldRecoverStaleRun) {
          autoRecoveredRunsRef.current.add(runId);
          await startRunFromTopic(topic, {
            clearArtifacts: true,
            warning: "이전 실행이 중간에 끊겨 자동으로 다시 시작했습니다.",
          });
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        runErrorRef.current = msg;
        setRunError(msg);
      }
    });

    return () => {
      mounted = false;
      if (unlistenRef.current) unlistenRef.current();
    };
  }, [runId, navigate, startRunFromTopic]);

  const completedCount = STAGES.filter((s) => stages[s].status === "completed").length;
  const totalProgress = (completedCount / STAGES.length) * 100;

  async function submitInterviewAnswer(answer: string, selected?: string, isOther = false) {
    if (!interviewPrompt || interviewSubmitting) return;
    const trimmed = answer.trim();
    if (!trimmed) {
      setInterviewError("답변을 입력하거나 선택하세요.");
      return;
    }
    setInterviewSubmitting(true);
    setInterviewError(null);
    try {
      await sendAction({
        action: "interview_answer",
        q_id: interviewPrompt.id,
        answer: trimmed,
        choice: selected ?? trimmed,
        selected: selected ?? trimmed,
        other_text: isOther ? trimmed : undefined,
      });
      setInterviewAnswer("");
      setInterviewSelections([]);
    } catch (err) {
      setInterviewError(err instanceof Error ? err.message : String(err));
      setInterviewSubmitting(false);
    }
  }

  async function submitSelectedOptions() {
    if (!interviewPrompt || interviewSelections.length === 0) {
      setInterviewError("선택지를 하나 이상 골라주세요.");
      return;
    }
    await submitInterviewAnswer(interviewSelections.join(", "), interviewSelections.join(","), false);
  }

  async function submitHitlDecision(status: "approved" | "changes_requested") {
    if (!hitlPrompt || hitlSubmitting) return;
    setHitlSubmitting(true);
    setHitlError(null);
    try {
      await sendAction({
        action: "hitl_decision",
        gate: hitlPrompt.gate,
        status,
      });
    } catch (err) {
      setHitlError(err instanceof Error ? err.message : String(err));
      setHitlSubmitting(false);
    }
  }

  async function abortRun() {
    if (aborting) return;
    setAborting(true);
    try {
      await sendAction({ action: "abort" });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      runErrorRef.current = message;
      setRunError(message);
    } finally {
      setAborting(false);
    }
  }

  async function restartRun() {
    if (!runId) return;
    const runTopic = topic || localStorage.getItem(`run:${runId}:topic`) || "";
    await startRunFromTopic(runTopic, { clearArtifacts: true });
  }

  return (
    <div className="min-h-screen px-6 py-10">
      <div className="mx-auto max-w-3xl">
        {/* Header */}
        <div className="fade-in mb-8">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <h1 className="truncate text-xl font-semibold tracking-tight text-white">
                {topic || "(주제 없음)"}
              </h1>
              <p className="mt-1 text-xs text-tertiary">{runId}</p>
            </div>
            <button
              type="button"
              onClick={abortRun}
              disabled={aborting}
              className="shrink-0 rounded-full border border-red-400/20 px-3 py-1.5 text-xs text-red-200 transition hover:bg-red-500/10 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {aborting ? "중단 중" : "중단"}
            </button>
          </div>
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
            <div className="flex shrink-0 items-center gap-2">
              <button
                type="button"
                onClick={restartRun}
                className="rounded-full bg-white px-3 py-1 text-xs font-medium text-black transition hover:opacity-90"
              >
                다시 시작
              </button>
              <button
                type="button"
                onClick={() => navigate("/")}
                className="rounded-full border border-white/10 px-3 py-1 text-xs text-secondary transition hover:bg-white/5 hover:text-white"
              >
                처음으로
              </button>
            </div>
          </div>
        )}

        {runWarnings.length > 0 && !runError && (
          <div className="fade-in mb-6 rounded-xl border border-amber-400/20 bg-amber-400/5 px-4 py-3">
            <p className="mb-1 text-xs font-medium uppercase tracking-wider text-amber-200">
              실행 경고
            </p>
            {runWarnings.map((warning) => (
              <p key={warning} className="break-all text-sm text-amber-100/80">
                {warning}
              </p>
            ))}
          </div>
        )}

        {/* Inline HITL approval card */}
        {hitlPrompt && (
          <div className="fade-in mb-6 overflow-hidden rounded-xl border border-amber-400/20 bg-amber-400/5 px-4 py-4">
            <div className="mb-3 flex items-start justify-between gap-4">
              <div className="min-w-0">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-amber-200">
                  HITL Gate · {hitlPrompt.gate}
                </p>
                <h2 className="mt-1 text-sm font-medium leading-relaxed text-white">
                  {hitlPrompt.title}
                </h2>
                <p className="mt-1 text-xs leading-relaxed text-secondary">
                  {hitlPrompt.prompt}
                </p>
              </div>
              <span className="shrink-0 whitespace-nowrap rounded-full border border-amber-400/20 bg-amber-400/10 px-2.5 py-1 text-[10px] text-amber-200">
                승인 대기
              </span>
            </div>

            {hitlPrompt.preview && (
              <pre className="mb-3 max-h-64 max-w-full overflow-auto whitespace-pre-wrap break-words rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs leading-relaxed text-secondary">
                {hitlPrompt.preview}
              </pre>
            )}

            <div className="grid grid-cols-1 gap-2 sm:ml-auto sm:inline-grid sm:max-w-full sm:grid-cols-[max-content_max-content]">
              <button
                type="button"
                disabled={hitlSubmitting}
                onClick={() => submitHitlDecision("changes_requested")}
                className="min-h-10 min-w-0 max-w-full whitespace-nowrap rounded-full border border-white/10 px-4 py-2 text-center text-sm text-secondary transition hover:bg-white/5 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
              >
                수정 필요
              </button>
              <button
                type="button"
                disabled={hitlSubmitting}
                onClick={() => submitHitlDecision("approved")}
                className="min-h-10 min-w-0 max-w-full whitespace-nowrap rounded-full bg-white px-4 py-2 text-center text-sm font-medium text-black transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {hitlSubmitting ? "승인 중" : "승인하고 계속"}
              </button>
            </div>

            {hitlError && <p className="mt-2 break-all text-xs text-red-300">{hitlError}</p>}
          </div>
        )}

        {/* Inline HITL/interview answer card */}
        {interviewPrompt && (
          <div className="fade-in mb-6 overflow-hidden rounded-xl border border-white/10 bg-white/[0.03] px-4 py-4">
            <div className="mb-3 flex items-start justify-between gap-4">
              <div className="min-w-0">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-tertiary">
                  {interviewPrompt.header}
                  {interviewPrompt.index && interviewPrompt.total
                    ? ` · ${interviewPrompt.index}/${interviewPrompt.total}`
                    : ""}
                </p>
                <h2 className="mt-1 whitespace-pre-wrap text-sm font-medium leading-relaxed text-white">
                  {interviewPrompt.text}
                </h2>
              </div>
              <span className="shrink-0 whitespace-nowrap rounded-full border border-amber-400/20 bg-amber-400/10 px-2.5 py-1 text-[10px] text-amber-200">
                {interviewSubmitting ? "다음 질문 대기" : "대기 중"}
              </span>
            </div>

            {interviewPrompt.preview && (
              <pre className="mb-3 max-h-56 max-w-full overflow-auto whitespace-pre-wrap break-words rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs leading-relaxed text-secondary">
                {interviewPrompt.preview}
              </pre>
            )}

            {interviewPrompt.options.length > 0 && (
              <div className="mb-3 grid gap-2 sm:grid-cols-2">
                {interviewPrompt.options.map((option) => (
                  <button
                    key={`${option.key}:${option.value}`}
                    type="button"
                    disabled={interviewSubmitting}
                    onClick={() => {
                      if (interviewPrompt.multiSelect) {
                        setInterviewSelections((prev) =>
                          prev.includes(option.value)
                            ? prev.filter((item) => item !== option.value)
                            : [...prev, option.value],
                        );
                      } else {
                        void submitInterviewAnswer(option.value, option.key);
                      }
                    }}
                    className={`rounded-lg border px-3 py-2 text-left text-xs transition disabled:cursor-not-allowed disabled:opacity-50 ${
                      interviewSelections.includes(option.value)
                        ? "border-white/30 bg-white/10 text-white"
                        : "border-white/10 bg-black/20 text-secondary hover:border-white/25 hover:bg-white/5 hover:text-white"
                    }`}
                  >
                    <span className="mr-2 font-mono text-white">{option.key}</span>
                    <span className="font-medium">{option.label}</span>
                    {option.description && (
                      <span className="mt-1 block text-[11px] leading-relaxed text-tertiary">
                        {option.description}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            )}

            {interviewPrompt.multiSelect && (
              <div className="mb-3 flex justify-end">
                <button
                  type="button"
                  disabled={interviewSubmitting || interviewSelections.length === 0}
                  onClick={submitSelectedOptions}
                  className="rounded-full bg-white px-4 py-2 text-sm font-medium text-black transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {interviewSubmitting ? "전송 중" : "선택 완료"}
                </button>
              </div>
            )}

            {interviewPrompt.allowOther && (
              <div className="flex flex-col gap-2 sm:flex-row">
                <input
                  value={interviewAnswer}
                  disabled={interviewSubmitting}
                  onChange={(event) => setInterviewAnswer(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") void submitInterviewAnswer(interviewAnswer, "OTHER", true);
                  }}
                  placeholder="직접 답변 입력"
                  className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm text-white placeholder-tertiary outline-none transition focus:border-white/30 focus:bg-black/30"
                />
                <button
                  type="button"
                  disabled={interviewSubmitting}
                  onClick={() => submitInterviewAnswer(interviewAnswer, "OTHER", true)}
                  className="rounded-full bg-white px-4 py-2 text-sm font-medium text-black transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {interviewSubmitting ? "전송 중" : "답변 전송"}
                </button>
              </div>
            )}

            {interviewError && (
              <p className="mt-2 break-all text-xs text-red-300">{interviewError}</p>
            )}
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

        {/* Live report preview */}
        {reportPreview && (
          <div className="fade-in mt-8 rounded-xl border border-white/5 bg-white/[0.02] p-4">
            <p className="mb-3 text-[11px] uppercase tracking-wider text-tertiary">
              Live report preview
            </p>
            <pre className="max-h-72 overflow-auto whitespace-pre-wrap text-xs leading-relaxed text-secondary">
              {reportPreview}
            </pre>
          </div>
        )}

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
