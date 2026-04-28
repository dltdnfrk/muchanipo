import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

interface KeyForm {
  label: string;
  key: string;
  type: "password" | "text";
}

const KEY_CONFIGS: KeyForm[] = [
  { label: "Anthropic API Key", key: "anthropic_api_key", type: "password" },
  { label: "Gemini API Key", key: "gemini_api_key", type: "password" },
  { label: "Kimi API Key", key: "kimi_api_key", type: "password" },
  { label: "OpenAlex Email", key: "openalex_email", type: "text" },
  { label: "Plannotator Key", key: "plannotator_key", type: "password" },
];

export default function Settings() {
  const [values, setValues] = useState<Record<string, string>>({});
  const [pipelineMode, setPipelineMode] = useState<"full" | "stub">("full");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const loaded: Record<string, string> = {};
    for (const cfg of KEY_CONFIGS) {
      loaded[cfg.key] = localStorage.getItem(cfg.key) || "";
    }
    setValues(loaded);
    setPipelineMode((localStorage.getItem("pipeline_mode") as "full" | "stub") || "full");
  }, []);

  const save = () => {
    for (const cfg of KEY_CONFIGS) {
      localStorage.setItem(cfg.key, values[cfg.key] || "");
    }
    localStorage.setItem("pipeline_mode", pipelineMode);
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  };

  const testConnection = () => {
    alert("Test Connection은 아직 구현되지 않았습니다. (placeholder)");
  };

  return (
    <div className="min-h-screen bg-[#15141B] px-4 py-10">
      <div className="mx-auto max-w-2xl">
        <div className="mb-8 flex items-center justify-between">
          <h1 className="text-2xl font-bold text-[#E8E0D0]">설정</h1>
          <Link
            to="/"
            className="rounded-lg border border-[#2A2833] bg-[#1E1D26] px-3 py-2 text-xs font-medium text-[#E8E0D0] transition hover:border-[#FFB347]"
          >
            ← 돌아가기
          </Link>
        </div>

        <div className="space-y-6">
          {/* API Keys */}
          <div className="rounded-xl border border-[#2A2833] bg-[#1E1D26] p-6">
            <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-[#FFB347]">
              API Keys
            </h2>
            <div className="space-y-4">
              {KEY_CONFIGS.map((cfg) => (
                <div key={cfg.key}>
                  <label className="mb-1 block text-xs font-medium text-[#C8C0B0]">
                    {cfg.label}
                  </label>
                  <input
                    type={cfg.type}
                    value={values[cfg.key] || ""}
                    onChange={(e) =>
                      setValues((v) => ({ ...v, [cfg.key]: e.target.value }))
                    }
                    className="w-full rounded-lg border border-[#2A2833] bg-[#15141B] px-3 py-2 text-sm text-[#E8E0D0] outline-none ring-[#FFB347] transition focus:ring-2"
                  />
                </div>
              ))}
            </div>
          </div>

          {/* Pipeline Mode */}
          <div className="rounded-xl border border-[#2A2833] bg-[#1E1D26] p-6">
            <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-[#FFB347]">
              Pipeline Mode
            </h2>
            <div className="flex items-center gap-4">
              <button
                onClick={() => setPipelineMode("full")}
                className={`rounded-lg border px-4 py-2 text-sm font-medium transition ${
                  pipelineMode === "full"
                    ? "border-[#FFB347] bg-[#FFB347] text-[#15141B]"
                    : "border-[#2A2833] bg-[#15141B] text-[#E8E0D0] hover:border-[#FFB347]"
                }`}
              >
                Full (8-stage MBB)
              </button>
              <button
                onClick={() => setPipelineMode("stub")}
                className={`rounded-lg border px-4 py-2 text-sm font-medium transition ${
                  pipelineMode === "stub"
                    ? "border-[#FFB347] bg-[#FFB347] text-[#15141B]"
                    : "border-[#2A2833] bg-[#15141B] text-[#E8E0D0] hover:border-[#FFB347]"
                }`}
              >
                Stub (빠른 테스트)
              </button>
            </div>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-3">
            <button
              onClick={save}
              className="rounded-lg bg-[#FFB347] px-5 py-2 text-sm font-semibold text-[#15141B] transition hover:bg-[#e6a03f]"
            >
              저장
            </button>
            <button
              onClick={testConnection}
              className="rounded-lg border border-[#2A2833] bg-[#1E1D26] px-5 py-2 text-sm font-medium text-[#E8E0D0] transition hover:border-[#FFB347]"
            >
              Test Connection
            </button>
            {saved && (
              <span className="text-xs text-green-400">저장되었습니다.</span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
