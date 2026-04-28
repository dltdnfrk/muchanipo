import { useEffect, useState } from "react";
import {
  checkCliSmoke,
  checkCliStatus,
  openCliAuth,
  type CliSmokeResult,
  type CliStatus,
} from "../lib/tauriClient";

interface KeyForm {
  label: string;
  key: string;
  type: "password" | "text";
  hint?: string;
}

const KEY_CONFIGS: KeyForm[] = [
  { label: "Anthropic API Key", key: "anthropic_api_key", type: "password", hint: "Council, Interview, Report 단계용" },
  { label: "OpenAI API Key", key: "openai_api_key", type: "password", hint: "Eval / Codex 단계 (CLI 없을 때)" },
  { label: "Gemini API Key", key: "gemini_api_key", type: "password", hint: "Intake, Targeting, Research 단계용" },
  { label: "Kimi API Key", key: "kimi_api_key", type: "password", hint: "Evidence 단계 (Moonshot)" },
  { label: "OpenAlex Email", key: "openalex_email", type: "text", hint: "polite pool 식별용 (무료 학술 API)" },
  { label: "Plannotator Key", key: "plannotator_key", type: "password", hint: "HITL 검토 (선택)" },
];

const CLI_HINTS: Record<string, string> = {
  claude: "claude auth login 으로 OAuth 로그인",
  codex: "codex login (또는 OPENAI_API_KEY 설정)",
  gemini: "gemini -i /auth 로 Google OAuth 로그인",
  kimi: "kimi login 으로 Moonshot OAuth 로그인",
};

const CLI_STAGE_MAP: Record<string, string> = {
  claude: "Anthropic — Council / Interview / Report",
  codex: "OpenAI — Eval / Critic",
  gemini: "Google — Intake / Research / Evidence",
  kimi: "Moonshot — Evidence",
};

export default function Settings() {
  const [values, setValues] = useState<Record<string, string>>({});
  const [pipelineMode, setPipelineMode] = useState<"full" | "stub">("full");
  const [backendMode, setBackendMode] = useState<"cli" | "api">("cli");
  const [saved, setSaved] = useState(false);
  const [cliStatuses, setCliStatuses] = useState<CliStatus[]>([]);
  const [cliLoading, setCliLoading] = useState(false);
  const [cliError, setCliError] = useState<string | null>(null);
  const [smokeResults, setSmokeResults] = useState<Record<string, CliSmokeResult>>({});
  const [smokeLoading, setSmokeLoading] = useState<Record<string, boolean>>({});
  const [authLoading, setAuthLoading] = useState<Record<string, boolean>>({});
  const [authMessage, setAuthMessage] = useState<string | null>(null);

  useEffect(() => {
    const loaded: Record<string, string> = {};
    for (const cfg of KEY_CONFIGS) loaded[cfg.key] = localStorage.getItem(cfg.key) || "";
    setValues(loaded);
    setPipelineMode((localStorage.getItem("pipeline_mode") as "full" | "stub") || "full");
    setBackendMode((localStorage.getItem("backend_mode") as "cli" | "api") || "cli");
  }, []);

  async function refreshCliStatus() {
    setCliLoading(true);
    setCliError(null);
    setSmokeResults({});
    try {
      const out = await checkCliStatus();
      setCliStatuses(out);
    } catch (err) {
      setCliError(err instanceof Error ? err.message : String(err));
    } finally {
      setCliLoading(false);
    }
  }

  async function runSmoke(name: string) {
    setSmokeLoading((prev) => ({ ...prev, [name]: true }));
    setSmokeResults((prev) => {
      const next = { ...prev };
      delete next[name];
      return next;
    });
    try {
      const out = await checkCliSmoke(name);
      setSmokeResults((prev) => ({ ...prev, [name]: out }));
    } catch (err) {
      setSmokeResults((prev) => ({
        ...prev,
        [name]: {
          name,
          ok: false,
          output: null,
          error: err instanceof Error ? err.message : String(err),
          timed_out: false,
        },
      }));
    } finally {
      setSmokeLoading((prev) => ({ ...prev, [name]: false }));
    }
  }

  async function connectCli(name: string) {
    setAuthLoading((prev) => ({ ...prev, [name]: true }));
    setAuthMessage(null);
    try {
      const launch = await openCliAuth(name);
      setAuthMessage(
        `${name} 로그인 창을 열었습니다. 실행 명령: ${launch.login_command}. 완료 후 다시 확인 또는 실호출 테스트를 눌러주세요.`,
      );
      window.setTimeout(() => {
        refreshCliStatus();
      }, 1000);
    } catch (err) {
      setAuthMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setAuthLoading((prev) => ({ ...prev, [name]: false }));
    }
  }

  useEffect(() => {
    if (backendMode === "cli") refreshCliStatus();
  }, [backendMode]);

  const save = () => {
    for (const cfg of KEY_CONFIGS) localStorage.setItem(cfg.key, values[cfg.key] || "");
    localStorage.setItem("pipeline_mode", pipelineMode);
    localStorage.setItem("backend_mode", backendMode);
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  };

  return (
    <div className="min-h-screen px-6 py-10">
      <div className="mx-auto max-w-2xl">
        <div className="fade-in mb-8">
          <h1 className="text-xl font-semibold tracking-tight text-white">설정</h1>
          <p className="mt-1 text-sm text-tertiary">
            로컬 CLI 또는 API 키로 LLM 백엔드를 연결하세요.
          </p>
        </div>

        {/* Backend mode toggle */}
        <section className="mb-8">
          <p className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-tertiary">
            Backend
          </p>
          <div className="flex gap-2">
            <button
              onClick={() => setBackendMode("cli")}
              className={`flex-1 rounded-lg border px-4 py-3 text-left text-sm transition ${
                backendMode === "cli"
                  ? "border-white/30 bg-white/10 text-white"
                  : "border-white/10 bg-white/[0.02] text-secondary hover:border-white/20 hover:text-white"
              }`}
            >
              <div className="font-medium">로컬 CLI</div>
              <div className="mt-0.5 text-[11px] text-tertiary">
                claude / codex / gemini OAuth 재사용 (권장)
              </div>
            </button>
            <button
              onClick={() => setBackendMode("api")}
              className={`flex-1 rounded-lg border px-4 py-3 text-left text-sm transition ${
                backendMode === "api"
                  ? "border-white/30 bg-white/10 text-white"
                  : "border-white/10 bg-white/[0.02] text-secondary hover:border-white/20 hover:text-white"
              }`}
            >
              <div className="font-medium">API Keys</div>
              <div className="mt-0.5 text-[11px] text-tertiary">
                직접 키를 발급해 사용 (서버 배포용)
              </div>
            </button>
          </div>
        </section>

        {/* CLI status (when in CLI mode) */}
        {backendMode === "cli" && (
          <section className="mb-8">
            <div className="mb-3 flex items-center justify-between">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-tertiary">
                CLI status
              </p>
              <button
                onClick={refreshCliStatus}
                disabled={cliLoading}
                className="text-[11px] text-secondary transition hover:text-white disabled:opacity-50"
              >
                {cliLoading ? "확인 중…" : "다시 확인"}
              </button>
            </div>
            {cliError && (
              <p className="mb-3 rounded-lg border border-red-500/20 bg-red-500/5 px-3 py-2 text-xs text-red-300">
                {cliError}
              </p>
            )}
            {authMessage && (
              <p className="mb-3 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-secondary">
                {authMessage}
              </p>
            )}
            <div className="overflow-hidden rounded-xl border border-white/5">
              {cliStatuses.length === 0 && !cliLoading && !cliError && (
                <p className="bg-white/[0.02] px-4 py-6 text-center text-xs text-tertiary">
                  상태를 확인하려면 "다시 확인"을 눌러주세요.
                </p>
              )}
              {cliStatuses.map((s, idx) => {
                const ok = s.installed && !s.error && !s.version_timed_out;
                const smoke = smokeResults[s.name];
                const canSmoke = Boolean(s.installed && s.smoke_supported);
                return (
                  <div
                    key={s.name}
                    className={`flex flex-col gap-3 bg-white/[0.02] px-4 py-3 sm:flex-row sm:items-start ${
                      idx > 0 ? "border-t border-white/5" : ""
                    }`}
                  >
                    <div className="flex min-w-0 flex-1 items-start gap-3">
                      <span
                        className={`mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-mono ${
                          ok
                            ? "bg-emerald-500/20 text-emerald-300"
                            : "bg-red-500/20 text-red-300"
                        }`}
                      >
                        {ok ? "✓" : "✗"}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-col gap-1 sm:flex-row sm:items-baseline sm:justify-between sm:gap-3">
                          <span className="font-mono text-sm text-white">{s.name}</span>
                          {s.version && (
                            <span className="min-w-0 truncate font-mono text-[10px] text-tertiary sm:text-right">
                              {s.version}
                            </span>
                          )}
                        </div>
                        <p className="mt-0.5 text-[11px] text-secondary">
                          {CLI_STAGE_MAP[s.name] || ""}
                        </p>
                        {!ok && (
                          <p className="mt-1 text-[11px] text-tertiary">
                            {s.error
                              ? s.error.split("\n")[0]
                              : `설치되지 않음 — ${CLI_HINTS[s.name] || ""}`}
                          </p>
                        )}
                        {ok && s.path && (
                          <p className="mt-0.5 truncate font-mono text-[10px] text-tertiary">
                            {s.path}
                          </p>
                        )}
                        {s.diagnosis && (
                          <p className="mt-1 text-[11px] text-tertiary">{s.diagnosis}</p>
                        )}
                        {!s.pipeline_supported && (
                          <p className="mt-1 text-[11px] text-amber-300">
                            파이프라인 자동 호출 미지원 — API 키 또는 mock fallback 사용
                          </p>
                        )}
                        {smoke && (
                          <p
                            className={`mt-2 break-all rounded-lg border px-3 py-2 text-[11px] ${
                              smoke.ok
                                ? "border-emerald-500/20 bg-emerald-500/5 text-emerald-300"
                                : "border-red-500/20 bg-red-500/5 text-red-300"
                            }`}
                          >
                            {smoke.ok
                              ? `실호출 OK${smoke.output ? ` — ${smoke.output.slice(0, 160)}` : ""}`
                              : smoke.error || "실호출 실패"}
                          </p>
                        )}
                      </div>
                    </div>
                    <div className="ml-8 flex shrink-0 gap-2 sm:ml-0 sm:flex-col sm:items-end">
                      <button
                        type="button"
                        onClick={() => connectCli(s.name)}
                        disabled={!s.installed || authLoading[s.name]}
                        className="w-fit whitespace-nowrap rounded-full border border-white/10 px-3 py-1 text-[11px] text-secondary transition hover:bg-white/5 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        {authLoading[s.name] ? "여는 중" : "연결"}
                      </button>
                      <button
                        type="button"
                        onClick={() => runSmoke(s.name)}
                        disabled={!canSmoke || smokeLoading[s.name]}
                        className="w-fit whitespace-nowrap rounded-full border border-white/10 px-3 py-1 text-[11px] text-secondary transition hover:bg-white/5 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        {smokeLoading[s.name] ? "테스트 중" : "실호출 테스트"}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
            <p className="mt-3 text-[11px] text-tertiary">
              "실호출 테스트"는 각 CLI에 짧은 실제 모델 호출을 보내므로 provider 정책에 따라 소량 과금될 수 있습니다.
            </p>
          </section>
        )}

        {/* API Keys section (when in API mode) */}
        {backendMode === "api" && (
          <section className="mb-8">
            <p className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-tertiary">
              API Keys
            </p>
            <div className="overflow-hidden rounded-xl border border-white/5">
              {KEY_CONFIGS.map((cfg, idx) => (
                <div
                  key={cfg.key}
                  className={`bg-white/[0.02] px-4 py-3 ${
                    idx > 0 ? "border-t border-white/5" : ""
                  }`}
                >
                  <label htmlFor={cfg.key} className="mb-1 block text-xs text-secondary">
                    {cfg.label}
                  </label>
                  <input
                    id={cfg.key}
                    type={cfg.type}
                    value={values[cfg.key] || ""}
                    onChange={(e) =>
                      setValues((v) => ({ ...v, [cfg.key]: e.target.value }))
                    }
                    placeholder={cfg.type === "password" ? "sk-..." : ""}
                    className="w-full rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm text-white placeholder-tertiary outline-none transition focus:border-white/30 focus:bg-black/30"
                  />
                  {cfg.hint && (
                    <p className="mt-1 text-[11px] text-tertiary">{cfg.hint}</p>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Pipeline mode */}
        <section className="mb-8">
          <p className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-tertiary">
            Pipeline mode
          </p>
          <div className="flex gap-2">
            <button
              onClick={() => setPipelineMode("full")}
              className={`flex-1 rounded-lg border px-4 py-3 text-left text-sm transition ${
                pipelineMode === "full"
                  ? "border-white/30 bg-white/10 text-white"
                  : "border-white/10 bg-white/[0.02] text-secondary hover:border-white/20 hover:text-white"
              }`}
            >
              <div className="font-medium">Full</div>
              <div className="mt-0.5 text-[11px] text-tertiary">
                8-stage MBB 보고서 (실제 사용)
              </div>
            </button>
            <button
              onClick={() => setPipelineMode("stub")}
              className={`flex-1 rounded-lg border px-4 py-3 text-left text-sm transition ${
                pipelineMode === "stub"
                  ? "border-white/30 bg-white/10 text-white"
                  : "border-white/10 bg-white/[0.02] text-secondary hover:border-white/20 hover:text-white"
              }`}
            >
              <div className="font-medium">Stub</div>
              <div className="mt-0.5 text-[11px] text-tertiary">
                빠른 테스트 (4 phase 플레이스홀더)
              </div>
            </button>
          </div>
        </section>

        {/* Actions */}
        <div className="flex items-center gap-3">
          <button
            onClick={save}
            className="rounded-full bg-white px-5 py-2 text-sm font-medium text-black transition hover:opacity-90"
          >
            저장
          </button>
          {saved && (
            <span className="fade-in text-xs text-secondary">저장됨</span>
          )}
        </div>
      </div>
    </div>
  );
}
