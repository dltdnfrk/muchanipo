import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import neobioLogoWhite from "../assets/neobio-logo-white.svg";
import {
  deleteRun,
  listRuns,
  subscribeRuns,
  type RunIndexEntry,
} from "../lib/runsIndex";

const COLLAPSED_KEY = "sidebar_collapsed";

function groupByDay(runs: RunIndexEntry[]): { label: string; items: RunIndexEntry[] }[] {
  const groups = new Map<string, RunIndexEntry[]>();
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const yesterday = today - 86_400_000;
  const weekAgo = today - 7 * 86_400_000;
  const monthAgo = today - 30 * 86_400_000;

  for (const r of runs) {
    let label: string;
    if (r.createdAt >= today) label = "Recents";
    else if (r.createdAt >= yesterday) label = "Yesterday";
    else if (r.createdAt >= weekAgo) label = "Last 7 days";
    else if (r.createdAt >= monthAgo) label = "Last 30 days";
    else label = "Older";
    const arr = groups.get(label) ?? [];
    arr.push(r);
    groups.set(label, arr);
  }
  const order = ["Recents", "Yesterday", "Last 7 days", "Last 30 days", "Older"];
  return order
    .filter((l) => groups.has(l))
    .map((l) => ({ label: l, items: groups.get(l)! }));
}

function parseActiveRunId(pathname: string): string | undefined {
  const m = pathname.match(/^\/(?:run|report|browser)\/([^/]+)/);
  return m?.[1];
}

function formatRunMeta(entry: RunIndexEntry): string {
  const date = entry.createdAt ? new Date(entry.createdAt) : null;
  const time = date
    ? date.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" })
    : "시간 없음";
  const state = entry.status === "running" ? "진행 중" : entry.status === "done" ? "완료" : "확인 필요";
  return `${state} · ${time}`;
}

function PanelLeftIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}>
      <rect x="3" y="4" width="18" height="16" rx="2.5" />
      <line x1="9" y1="4" x2="9" y2="20" />
    </svg>
  );
}

function SearchIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}>
      <circle cx="11" cy="11" r="6" />
      <path strokeLinecap="round" d="M16 16l4 4" />
    </svg>
  );
}

function NavRow({ icon, label, badge, to }: { icon: string; label: string; badge?: string; to?: string }) {
  const inner = (
    <>
      <span className="cowork-side-icon">{icon}</span>
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {badge && <span className="cowork-side-badge">{badge}</span>}
    </>
  );
  const cls = "cowork-side-row";
  return to ? <Link to={to} className={cls}>{inner}</Link> : <div className={cls}>{inner}</div>;
}

export default function Sidebar() {
  const [runs, setRuns] = useState<RunIndexEntry[]>(() => listRuns());
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem(COLLAPSED_KEY) === "1";
    } catch {
      return false;
    }
  });
  const navigate = useNavigate();
  const location = useLocation();
  const activeRunId = parseActiveRunId(location.pathname);

  useEffect(() => subscribeRuns(() => setRuns(listRuns())), []);

  function toggleCollapsed() {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(COLLAPSED_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  }

  function handleDelete(e: React.MouseEvent, runId: string) {
    e.preventDefault();
    e.stopPropagation();
    deleteRun(runId);
    if (activeRunId === runId) navigate("/");
  }

  if (collapsed) {
    return (
      <button
        onClick={toggleCollapsed}
        className="fixed left-4 top-10 z-50 flex h-8 w-8 items-center justify-center rounded-lg text-tertiary transition hover:bg-white/5 hover:text-white"
        title="사이드바 열기"
        aria-label="사이드바 열기"
      >
        <PanelLeftIcon className="h-5 w-5" />
      </button>
    );
  }

  const groups = groupByDay(runs);
  const isCowork =
    location.pathname.startsWith("/browser") ||
    location.pathname.startsWith("/run") ||
    location.pathname.startsWith("/report");

  return (
    <aside className="sidebar-shell cowork-sidebar flex h-screen w-[300px] shrink-0 flex-col">
      <div data-tauri-drag-region className="h-7 w-full shrink-0" />

      <div className="cowork-sidebar-top">
        <Link to="/studio" className="cowork-brand-link" aria-label="Neobio Studio 홈">
          <img src={neobioLogoWhite} alt="Neobio" className="cowork-brand-logo" />
        </Link>
        <div className="cowork-sidebar-actions">
          <button onClick={toggleCollapsed} className="cowork-icon-button" title="사이드바 닫기" aria-label="사이드바 닫기">
            <PanelLeftIcon className="h-5 w-5" />
          </button>
          <button className="cowork-icon-button" title="검색" aria-label="검색">
            <SearchIcon className="h-5 w-5" />
          </button>
        </div>
      </div>

      <div className="cowork-mode-switch two-up">
        <Link to="/studio" className={!isCowork ? "active" : ""}>Studio</Link>
        <Link to="/browser" className={isCowork ? "active" : ""}>Browser</Link>
      </div>

      <nav className="cowork-primary-nav">
        <NavRow icon="＋" label="New task" to="/studio" />
        <NavRow icon="▰" label="Projects" to="/browser" />
        <NavRow icon="◷" label="Scheduled" />
        <NavRow icon="⌁" label="Live artifacts" to="/browser" />
        <NavRow icon="▣" label="Dispatch" badge="베타" />
        <NavRow icon="▤" label="Customize" to="/settings" />
      </nav>

      <section className="cowork-sidebar-section">
        <p>Pinned</p>
        <div className="cowork-muted-row">♙ Drag to pin</div>
      </section>

      <nav className="cowork-history flex-1 overflow-y-auto">
        {runs.length === 0 ? (
          <section className="cowork-sidebar-section">
            <p>Recents</p>
            <div className="cowork-muted-row">○ Starting fresh new session</div>
          </section>
        ) : (
          groups.map((g) => (
            <section key={g.label} className="cowork-sidebar-section">
              <p>{g.label}</p>
              <ul>
                {g.items.map((r) => {
                  const targetPath = r.status === "done" ? `/browser/${r.runId}/report` : `/browser/${r.runId}`;
                  const isActive = activeRunId === r.runId;
                  const statusIcon = r.status === "failed" ? "⚠" : r.status === "running" ? "◉" : "○";
                  return (
                    <li key={r.runId}>
                      <Link to={targetPath} title={r.topic} className={`cowork-recent-task ${isActive ? "active" : ""}`}>
                        <span className={r.status}>{statusIcon}</span>
                        <span className="cowork-recent-copy">
                          <strong>{r.topic || "(주제 없음)"}</strong>
                          <small>{formatRunMeta(r)}</small>
                        </span>
                        {r.status === "running" && <em>진행</em>}
                        <button onClick={(e) => handleDelete(e, r.runId)} title="삭제" aria-label="Run 삭제">×</button>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))
        )}
      </nav>

      <footer className="cowork-sidebar-footer">
        <div className="cowork-avatar">현</div>
        <span>현준 · Max</span>
        <Link to="/settings" aria-label="설정">⚙</Link>
      </footer>
    </aside>
  );
}
