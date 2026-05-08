import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { markPendingRun } from "../lib/pendingRun";
import { pushRun } from "../lib/runsIndex";

function newRunId(): string {
  return `run-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function newStudioId(): string {
  return `studio-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

const STUDIO_STEPS = [
  ["Goal", "이해할 목표 입력"],
  ["Unknown", "모호한 개념 확인"],
  ["Evidence", "근거 경계 설정"],
  ["Run", "Browser 실행 준비"],
] as const;

const BROWSER_PREVIEW = [
  ["Status", "Locked"],
  ["Input", "Studio graph required"],
  ["Next", "Evidence · Run · Report"],
] as const;

export default function IdeaSubmit() {
  const [idea, setIdea] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    if (!import.meta.env.DEV) return;
    const autostartTopic = (import.meta.env.VITE_MUCHANIPO_AUTOSTART_TOPIC || "").trim();
    if (!autostartTopic) return;
    const sessionKey = `muchanipo:autostart:${autostartTopic}`;
    if (sessionStorage.getItem(sessionKey)) return;
    sessionStorage.setItem(sessionKey, "1");
    const runId = newRunId();
    try {
      localStorage.setItem(`run:${runId}:topic`, autostartTopic);
      markPendingRun(runId);
      pushRun(runId, autostartTopic);
    } catch {
      /* ignore */
    }
    navigate(`/browser/${runId}`);
  }, [navigate]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    const trimmed = idea.trim();
    if (!trimmed) {
      setError("아이디어를 한 문장으로 입력해주세요.");
      return;
    }
    setLoading(true);
    try {
      const studioId = newStudioId();
      try {
        localStorage.setItem(`studio:${studioId}:goal`, trimmed);
      } catch {
        /* ignore */
      }
      navigate(`/studio/${studioId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "제출 중 오류가 발생했습니다.");
      setLoading(false);
    }
  }

  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center px-6 py-10">
      {/* Top-right settings */}
      <Link
        to="/settings"
        className="absolute right-4 top-4 rounded-md border border-white/10 bg-white/[0.03] p-2 text-tertiary transition hover:bg-white/5 hover:text-white"
        title="설정"
      >
        <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
          <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
      </Link>

      <div className="fade-in w-full max-w-6xl">
        <div className="mb-6 grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px] lg:items-end">
          <div>
            <p className="atlas-label mb-2">Muchanipo Studio</p>
            <h1 className="display-serif max-w-3xl text-[40px] font-semibold leading-tight text-white sm:text-[56px]">
              Start with a Goal.
            </h1>
            <p className="mt-4 max-w-2xl text-[15px] leading-7 text-secondary">
              Describe the Goal in one sentence. Studio will clarify unknowns and evidence boundaries before Browser runs.
            </p>
          </div>
          <div className="rounded-lg border border-white/10 bg-white/[0.025] px-4 py-3">
            <div className="flex items-center justify-between gap-3">
              <span className="text-xs font-semibold uppercase tracking-[0.16em] text-tertiary">Browser</span>
              <span className="min-w-[72px] rounded-full border border-white/10 bg-black/20 px-2 py-1 text-center font-mono text-[10px] uppercase tracking-[0.12em] text-tertiary">
                Locked
              </span>
            </div>
            <p className="mt-2 text-xs leading-5 text-secondary">
              Browser opens after Studio has a graph to run.
            </p>
          </div>
        </div>

        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
          <section>
            <form onSubmit={handleSubmit}>
              <div className="research-composer group p-2 transition focus-within:border-white/20">
                <textarea
                  value={idea}
                  onChange={(e) => setIdea(e.target.value)}
                  rows={5}
                  placeholder="Describe the Goal in one sentence."
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                      handleSubmit(e as unknown as React.FormEvent);
                    }
                  }}
                  className="w-full resize-none rounded-[20px] bg-transparent px-5 py-5 text-[18px] leading-8 text-white placeholder-tertiary outline-none"
                  disabled={loading}
                />
                <div className="flex items-center justify-between border-t border-white/10 px-4 py-3">
                  <p className="text-xs text-tertiary">
                    <kbd className="rounded-md border border-white/10 bg-white/5 px-1.5 py-0.5 font-mono text-[10px]">
                      ⌘
                    </kbd>
                    <kbd className="ml-1 rounded-md border border-white/10 bg-white/5 px-1.5 py-0.5 font-mono text-[10px]">
                      ↵
                    </kbd>
                    <span className="ml-1.5">Studio 시작</span>
                  </p>
                <button
                  type="submit"
                  aria-label="Start Studio"
                  title="Start Studio"
                  disabled={loading || !idea.trim()}
                  className="flex h-9 w-9 items-center justify-center rounded-full border border-[#f4efe6] bg-[#f4efe6] text-[#1f1f1d] transition hover:bg-white disabled:cursor-not-allowed disabled:opacity-30"
                >
                  {loading ? (
                    <svg className="h-3.5 w-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
                      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.3" strokeWidth="3" />
                      <path d="M12 2a10 10 0 0110 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
                    </svg>
                  ) : (
                    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M12 4l-1.4 1.4 5.6 5.6H4v2h12.2l-5.6 5.6L12 20l8-8-8-8z" />
                    </svg>
                  )}
                </button>
            </div>
          </div>
        </form>

        {error && (
          <div className="fade-in mt-3 rounded-lg border border-red-500/20 bg-red-500/5 px-4 py-3 text-sm text-red-300">
            {error}
          </div>
        )}

            <div className="mt-4 grid gap-2 sm:grid-cols-4">
              {STUDIO_STEPS.map(([label, description]) => (
                <div key={label} className="rounded-lg border border-white/10 bg-white/[0.025] px-3 py-3">
                  <div className="text-sm font-medium text-white">{label}</div>
                  <div className="mt-1 text-xs leading-5 text-tertiary">{description}</div>
                </div>
              ))}
            </div>
          </section>

          <aside className="rounded-lg border border-white/10 bg-[#111213] p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-sm font-semibold text-white">Browser preview</h2>
                <p className="mt-1 text-xs leading-5 text-tertiary">Execution remains locked until Studio creates a graph.</p>
              </div>
              <span className="min-w-[72px] rounded-full border border-white/10 bg-black/30 px-2 py-1 text-center font-mono text-[10px] uppercase tracking-[0.12em] text-tertiary">
                Locked
              </span>
            </div>
            <div className="mt-4 space-y-2">
              {BROWSER_PREVIEW.map(([label, value]) => (
                <div key={label} className="grid grid-cols-[76px_1fr] gap-3 rounded-md border border-white/10 bg-black/20 px-3 py-2 text-xs">
                  <span className="font-mono uppercase tracking-[0.08em] text-tertiary">{label}</span>
                  <span className="truncate text-secondary">{value}</span>
                </div>
              ))}
            </div>
            <div className="mt-4 grid grid-cols-3 gap-2 text-center text-[11px]">
              <div className="rounded-md border border-white/10 bg-black/20 px-2 py-2 text-tertiary">Evidence</div>
              <div className="rounded-md border border-white/10 bg-black/20 px-2 py-2 text-tertiary">Run</div>
              <div className="rounded-md border border-white/10 bg-black/20 px-2 py-2 text-tertiary">Report</div>
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}
