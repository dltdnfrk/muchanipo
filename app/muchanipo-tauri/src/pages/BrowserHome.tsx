import { Link } from "react-router-dom";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { listRuns, subscribeRuns, type RunIndexEntry } from "../lib/runsIndex";

function formatStatus(status: RunIndexEntry["status"]): string {
  switch (status) {
    case "running":
      return "진행";
    case "done":
      return "완료";
    case "failed":
      return "실패";
    default:
      return "대기";
  }
}

function statusToneClass(status: RunIndexEntry["status"]): string {
  switch (status) {
    case "running":
      return "border-[#c96442]/35 bg-[#c96442]/10 text-[#f0c7b3]";
    case "done":
      return "border-white/15 bg-white/[0.035] text-secondary";
    case "failed":
      return "border-red-400/25 bg-red-500/10 text-red-300";
    default:
      return "border-white/10 bg-white/[0.025] text-tertiary";
  }
}

function stageSummary(status: RunIndexEntry["status"] | undefined): { label: string; detail: string; progress: number } {
  switch (status) {
    case "running":
      return {
        label: "근거 수집 중",
        detail: "실시간 신호를 받으며 출처를 찾고 평가하고 있어요.",
        progress: 46,
      };
    case "done":
      return {
        label: "보고서 준비 완료",
        detail: "근거와 판단을 모아 최종 보고서로 정리했어요.",
        progress: 100,
      };
    case "failed":
      return {
        label: "확인 필요",
        detail: "실행 중 문제가 생겼어요. 진행 화면에서 원인을 확인하세요.",
        progress: 24,
      };
    default:
      return {
        label: "새 조사를 시작하세요",
        detail: "Studio에서 목표를 정리하면 Browser가 이어서 실행합니다.",
        progress: 0,
      };
  }
}

export default function BrowserHome() {
  const [runs, setRuns] = useState<RunIndexEntry[]>(() => listRuns());

  useEffect(() => subscribeRuns(() => setRuns(listRuns())), []);

  useEffect(() => {
    const workspace = document.querySelector("main.app-workspace");
    workspace?.scrollTo({ top: 0, left: 0 });
    window.scrollTo({ top: 0, left: 0 });
  }, []);

  const activeRun = useMemo(
    () => runs.find((r) => r.status === "running") ?? runs[0] ?? null,
    [runs],
  );
  const target = activeRun
    ? activeRun.status === "done"
      ? `/browser/${activeRun.runId}/report`
      : `/browser/${activeRun.runId}`
    : "/studio";
  const summary = stageSummary(activeRun?.status);
  const completedCount = activeRun?.status === "done" ? 10 : activeRun?.status === "running" ? 4 : activeRun?.status === "failed" ? 2 : 0;

  return (
    <div className="muchanipo-cowork-shell min-h-[calc(100vh-49px)]">
      <section className="cowork-center">
        <header className="cowork-titlebar">
          <Link to="/studio" className="cowork-title-main">
            {activeRun?.topic ? "시장성 근거 조사" : "Muchanipo Browser"}
            <span aria-hidden="true" className="ml-2 text-tertiary">⌄</span>
          </Link>
          <div className="cowork-title-actions" aria-label="Browser sections">
            <span className="active">실시간 결과</span>
            <span>근거</span>
            <span>보고서</span>
          </div>
        </header>

        <div className="cowork-thread">
          <div className="cowork-user-bubble">
            딸기 농가용 저비용 분자진단 키트의 시장성과 실제 근거를 확인하고 싶어.
          </div>

          <article className="cowork-assistant-message">
            <div className="cowork-stage-hero">
              <p className="atlas-label">현재 상태</p>
              <h1>{summary.label}</h1>
              <p>{summary.detail}</p>
              <div className="cowork-progress-bar" aria-label={`진행률 ${summary.progress}%`}>
                <span style={{ width: `${summary.progress}%` }} />
              </div>
              <small>{completedCount}/10 단계 · {activeRun?.status === "running" ? "최근 신호 수신 중" : "대기 중"}</small>
            </div>
            <p>
              Studio에서 <strong>목표와 모호한 조건을 정리</strong>하면 Browser가
              <strong> 실행 → 근거 수집 → 보고서</strong> 순서로 진행합니다.
            </p>
            <p>
              실행 중에는 <code>실행 중</code>, <code>출처 발견</code>,
              <code>출처 평가 완료</code>, <code>보고서 생성</code> 같은 신호를 남겨서
              지금 실제로 작업 중인지 바로 볼 수 있게 합니다.
            </p>
            <p>
              출처 채택/거절, 보고서 생성 여부, 연결된 파일과 커넥터는 오른쪽 컨텍스트 패널에 계속 쌓입니다.
            </p>
          </article>

          <div className="cowork-chat-actions">
            <Link to={target} className="cowork-primary-action">
              {activeRun ? "실시간 조사 화면 열기" : "새 조사 시작"}
            </Link>
          </div>
        </div>

        <div className="cowork-composer-wrap">
          <Link to="/studio" className="cowork-composer">
            <div className="cowork-composer-placeholder">
              {activeRun ? "현재 조사에 추가 지시를 입력하세요…" : "무엇을 조사할까요…"}
            </div>
            <div className="cowork-composer-footer">
              <div className="flex items-center gap-4">
                <span className="text-2xl leading-none">＋</span>
                <span className="cowork-mode-chip">추가 조사 ⌄</span>
              </div>
              <div className="flex items-center gap-4">
                <span className="text-tertiary">Deep research ⌄</span>
                <span className="text-xl">⌁</span>
              </div>
            </div>
          </Link>
          <p className="cowork-disclaimer">
            Muchanipo는 AI이므로 실수할 수 있습니다. 중요한 농업·시장성 판단은 다시 확인해 주세요.
          </p>
        </div>
      </section>

      <aside className="cowork-context-panel">
        <ContextCard>
          <div className="cowork-card-row">
            <span>진행 상황</span>
            <span>{completedCount}/10 ›</span>
          </div>
          <div className="cowork-current-run-card">
            <p>{activeRun?.topic || "새로운 Goal을 정리하세요"}</p>
            <div className="cowork-progress-bar compact" aria-hidden="true">
              <span style={{ width: `${summary.progress}%` }} />
            </div>
            <small>{summary.label}</small>
            <span className={`cowork-status-pill ${statusToneClass(activeRun?.status ?? "pending")}`}>
              {formatStatus(activeRun?.status ?? "pending")}
            </span>
            <Link to={target}>상세 보기</Link>
          </div>
        </ContextCard>

        <ContextCard>
          <div className="cowork-card-row">
            <span>Hyunjun</span>
            <span>▣ ›</span>
          </div>
        </ContextCard>

        <ContextCard title="컨텍스트">
          <ContextSection label="업로드">
            <ContextItem icon="MD" label="REPORT.md" />
            <ContextItem icon="JSON" label="pipeline events" />
          </ContextSection>
          <ContextSection label="커넥터">
            <ContextItem icon="⌘" label="Tauri desktop" />
            <ContextItem icon="Py" label="Python backend" />
            <ContextItem icon="Web" label="Source research" />
            <ContextItem icon="Vault" label="Obsidian/Vault" />
          </ContextSection>
        </ContextCard>
      </aside>
    </div>
  );
}

function ContextCard({
  title,
  children,
}: {
  title?: string;
  children: ReactNode;
}) {
  return (
    <section className="cowork-context-card">
      {title && <h2>{title}</h2>}
      {children}
    </section>
  );
}

function ContextSection({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="cowork-context-section">
      <p>{label}</p>
      <div>{children}</div>
    </div>
  );
}

function ContextItem({ icon, label }: { icon: string; label: string }) {
  return (
    <div className="cowork-context-item">
      <span>{icon}</span>
      <strong>{label}</strong>
    </div>
  );
}
