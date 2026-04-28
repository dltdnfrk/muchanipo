import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
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
    if (r.createdAt >= today) label = "오늘";
    else if (r.createdAt >= yesterday) label = "어제";
    else if (r.createdAt >= weekAgo) label = "지난 7일";
    else if (r.createdAt >= monthAgo) label = "지난 30일";
    else label = "이전";
    const arr = groups.get(label) ?? [];
    arr.push(r);
    groups.set(label, arr);
  }
  const order = ["오늘", "어제", "지난 7일", "지난 30일", "이전"];
  return order
    .filter((l) => groups.has(l))
    .map((l) => ({ label: l, items: groups.get(l)! }));
}

function parseActiveRunId(pathname: string): string | undefined {
  const m = pathname.match(/^\/(?:run|report)\/([^/]+)/);
  return m?.[1];
}

function PanelLeftIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}>
      <rect x="3" y="4" width="18" height="16" rx="2.5" />
      <line x1="9" y1="4" x2="9" y2="20" />
    </svg>
  );
}

function NewChatIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 3.5a2.121 2.121 0 113 3L7 19l-4 1 1-4 12.5-12.5z" />
    </svg>
  );
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

  // Collapsed: render only a floating expand button on the very left edge.
  if (collapsed) {
    return (
      <button
        onClick={toggleCollapsed}
        className="fixed left-2 top-2 z-40 flex h-8 w-8 items-center justify-center rounded-lg text-tertiary transition hover:bg-white/5 hover:text-white"
        title="사이드바 열기"
        aria-label="사이드바 열기"
      >
        <PanelLeftIcon className="h-5 w-5" />
      </button>
    );
  }

  const groups = groupByDay(runs);

  return (
    <aside className="flex h-screen w-[260px] shrink-0 flex-col bg-[#171717]">
      {/* Top bar: collapse + new chat */}
      <div className="flex items-center justify-between px-2 pt-2">
        <button
          onClick={toggleCollapsed}
          className="flex h-8 w-8 items-center justify-center rounded-lg text-tertiary transition hover:bg-white/5 hover:text-white"
          title="사이드바 닫기"
          aria-label="사이드바 닫기"
        >
          <PanelLeftIcon className="h-5 w-5" />
        </button>
        <Link
          to="/"
          className="flex h-8 w-8 items-center justify-center rounded-lg text-tertiary transition hover:bg-white/5 hover:text-white"
          title="새 리서치"
          aria-label="새 리서치"
        >
          <NewChatIcon className="h-[18px] w-[18px]" />
        </Link>
      </div>

      {/* "+ 새 리서치" pill row */}
      <div className="px-2 pt-1">
        <Link
          to="/"
          className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-[14px] text-secondary transition hover:bg-white/5 hover:text-white"
        >
          <NewChatIcon className="h-4 w-4" />
          <span>새 리서치</span>
        </Link>
      </div>

      {/* History */}
      <nav className="mt-2 flex-1 overflow-y-auto px-2 pb-2">
        {runs.length === 0 ? (
          <div className="px-3 py-8 text-center text-[12px] text-tertiary">
            아직 리서치 기록이 없어요
          </div>
        ) : (
          groups.map((g) => (
            <div key={g.label} className="mt-3 first:mt-0">
              <p className="px-3 pb-1 text-[11px] font-medium text-tertiary">
                {g.label}
              </p>
              <ul>
                {g.items.map((r) => {
                  const targetPath =
                    r.status === "done" ? `/report/${r.runId}` : `/run/${r.runId}`;
                  const isActive = activeRunId === r.runId;
                  return (
                    <li key={r.runId}>
                      <Link
                        to={targetPath}
                        className={`group relative flex items-center rounded-lg pl-3 pr-2 py-2 text-[14px] leading-tight transition ${
                          isActive
                            ? "bg-white/[0.07] text-white"
                            : "text-secondary hover:bg-white/[0.04] hover:text-white"
                        }`}
                        title={r.topic}
                      >
                        <span className="truncate flex-1">{r.topic || "(주제 없음)"}</span>
                        <button
                          onClick={(e) => handleDelete(e, r.runId)}
                          className="ml-1 hidden h-6 w-6 shrink-0 items-center justify-center rounded-md text-tertiary transition hover:bg-white/10 hover:text-white group-hover:flex"
                          title="삭제"
                          aria-label="리서치 삭제"
                        >
                          <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6M3 7h18M9 7V4a2 2 0 012-2h2a2 2 0 012 2v3" />
                          </svg>
                        </button>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))
        )}
      </nav>

      {/* Footer */}
      <div className="px-2 pb-2">
        <Link
          to="/settings"
          className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-[14px] transition ${
            location.pathname === "/settings"
              ? "bg-white/[0.07] text-white"
              : "text-secondary hover:bg-white/[0.04] hover:text-white"
          }`}
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
          <span>설정</span>
        </Link>
      </div>
    </aside>
  );
}
