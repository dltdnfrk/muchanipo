import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { type PipelineMode, submitIdea } from "../lib/tauriClient";

function newRunId(): string {
  return `run-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function readPipelineMode(): PipelineMode {
  const value = localStorage.getItem("pipeline_mode");
  return value === "stub" ? "stub" : "full";
}

function readPipelineEnvs(): Record<string, string> {
  const mappings: Array<[string, string]> = [
    ["anthropic_api_key", "ANTHROPIC_API_KEY"],
    ["gemini_api_key", "GEMINI_API_KEY"],
    ["kimi_api_key", "KIMI_API_KEY"],
    ["openalex_email", "MUCHANIPO_CONTACT_EMAIL"],
    ["plannotator_key", "PLANNOTATOR_API_KEY"],
  ];
  return Object.fromEntries(
    mappings
      .map(([storageKey, envKey]) => [envKey, localStorage.getItem(storageKey)?.trim() || ""] as const)
      .filter(([, value]) => value.length > 0),
  );
}

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
      setError("아이디어를 입력해주세요.");
      return;
    }

    setLoading(true);
    try {
      const runId = newRunId();
      // store the topic so RunProgress / ReportView can show it
      try {
        localStorage.setItem(`run:${runId}:topic`, trimmed);
      } catch {
        /* private mode etc. — ignore */
      }
      await submitIdea(trimmed, readPipelineMode(), readPipelineEnvs());
      navigate(`/run/${runId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "제출 중 오류가 발생했습니다.");
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-[#15141B] px-4">
      <div className="w-full max-w-2xl">
        <h1 className="mb-2 text-center text-3xl font-bold text-[#E8E0D0]">
          Muchanipo
        </h1>
        <p className="mb-8 text-center text-sm text-[#8A8599]">
          아이디어만 던지면 자동으로 리서치 → 심의 → 보고서를 완성합니다.
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <textarea
            value={idea}
            onChange={(e) => setIdea(e.target.value)}
            rows={12}
            placeholder="예: 딸기 농가용 저비용 분자진단 키트 시장성을 알아보고 싶다"
            className="w-full resize-none rounded-xl border border-[#2A2833] bg-[#1E1D26] p-4 text-base text-[#E8E0D0] placeholder-[#5A5669] outline-none ring-[#FFB347] transition focus:ring-2"
          />

          {error && <p className="text-sm text-red-400">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-xl bg-[#FFB347] py-3 text-base font-semibold text-[#15141B] transition hover:bg-[#e6a03f] disabled:opacity-60"
          >
            {loading ? "제출 중…" : "리서치 시작"}
          </button>
        </form>
      </div>
    </div>
  );
}
