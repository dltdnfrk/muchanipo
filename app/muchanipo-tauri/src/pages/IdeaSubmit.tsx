import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import logoUrl from "../assets/neobio-logo-white.svg";
import { pushRun } from "../lib/runsIndex";

function newRunId(): string {
  return `run-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

const SAMPLES = [
  "딸기 농가용 저비용 분자진단 키트 시장성",
  "한국 65세 이상 1인 가구 재택의료 SaaS",
  "Z세대 친환경 패션 D2C 브랜드",
  "AI 코딩 어시스턴트 기업용 보안 게이트웨이",
];

export default function IdeaSubmit() {
  const [idea, setIdea] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

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
      const runId = newRunId();
      try {
        // Persist topic + pending flag so RunProgress can pick up the run and
        // start the pipeline AFTER its event listener has registered. Doing
        // it here (before listener) caused the listener to miss events when
        // the pipeline finished faster than the page transition.
        localStorage.setItem(`run:${runId}:topic`, trimmed);
        localStorage.setItem(`run:${runId}:pending`, "1");
        pushRun(runId, trimmed);
      } catch {
        /* ignore */
      }
      navigate(`/run/${runId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "제출 중 오류가 발생했습니다.");
      setLoading(false);
    }
  }

  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center px-6">
      {/* Top-right settings */}
      <Link
        to="/settings"
        className="absolute right-4 top-4 rounded-md p-2 text-tertiary transition hover:bg-white/5 hover:text-white"
        title="설정"
      >
        <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
          <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
      </Link>

      <div className="fade-in w-full max-w-2xl">
        {/* Centered hero — ChatGPT empty state style */}
        <div className="mb-10 flex flex-col items-center text-center">
          <img src={logoUrl} alt="NeoBio" className="mb-6 h-28 w-auto" />
          <h1 className="text-2xl font-semibold tracking-tight text-white">
            오늘 어떤 주제를 리서치할까요?
          </h1>
        </div>

        {/* Composer (ChatGPT input box style) */}
        <form onSubmit={handleSubmit}>
          <div className="surface group rounded-2xl p-2 transition focus-within:border-white/20">
            <textarea
              value={idea}
              onChange={(e) => setIdea(e.target.value)}
              rows={3}
              placeholder="예: 딸기 농가용 저비용 분자진단 키트 시장성"
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                  handleSubmit(e as unknown as React.FormEvent);
                }
              }}
              className="w-full resize-none rounded-xl bg-transparent px-3 py-2.5 text-[15px] leading-relaxed text-white placeholder-tertiary outline-none"
              disabled={loading}
            />
            <div className="flex items-center justify-between px-2 py-1">
              <p className="text-xs text-tertiary">
                <kbd className="rounded border border-white/10 bg-white/5 px-1.5 py-0.5 font-mono text-[10px]">
                  ⌘
                </kbd>
                <kbd className="ml-1 rounded border border-white/10 bg-white/5 px-1.5 py-0.5 font-mono text-[10px]">
                  ↵
                </kbd>
                <span className="ml-1.5">to send</span>
              </p>
              <button
                type="submit"
                disabled={loading || !idea.trim()}
                className="flex h-8 w-8 items-center justify-center rounded-full bg-white text-black transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-30"
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

        {/* Suggested prompts */}
        <div className="mt-8 flex flex-wrap justify-center gap-2">
          {SAMPLES.map((sample) => (
            <button
              key={sample}
              type="button"
              onClick={() => setIdea(sample)}
              className="rounded-full border border-white/10 bg-transparent px-3.5 py-1.5 text-xs text-secondary transition hover:bg-white/5 hover:text-white"
            >
              {sample}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
