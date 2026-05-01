// Lightweight persistent index of research runs, used to render the sidebar
// history. Each run carries the topic + creation timestamp + last route the
// user visited (run vs report) so clicking restores the right page.
//
// Storage key: `runs_index` -> JSON array of RunIndexEntry, newest-first.

const KEY = "runs_index";
const MAX_ENTRIES = 200;

export interface RunIndexEntry {
  runId: string;
  topic: string;
  createdAt: number;
  status: "running" | "done";
}

export function listRuns(): RunIndexEntry[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (e): e is RunIndexEntry =>
        typeof e?.runId === "string" && typeof e?.topic === "string",
    );
  } catch {
    return [];
  }
}

function writeRuns(entries: RunIndexEntry[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(entries.slice(0, MAX_ENTRIES)));
    // Notify listeners in the same tab (storage event only fires cross-tab).
    window.dispatchEvent(new CustomEvent("runs_index_changed"));
  } catch {
    /* ignore quota */
  }
}

export function pushRun(runId: string, topic: string): void {
  const now = Date.now();
  const existing = listRuns().filter((e) => e.runId !== runId);
  writeRuns([
    { runId, topic, createdAt: now, status: "running" },
    ...existing,
  ]);
}

export function markRunDone(runId: string): void {
  const entries = listRuns().map((e) =>
    e.runId === runId ? { ...e, status: "done" as const } : e,
  );
  writeRuns(entries);
}

export function markRunRunning(runId: string): void {
  const entries = listRuns().map((e) =>
    e.runId === runId ? { ...e, status: "running" as const } : e,
  );
  writeRuns(entries);
}

export function deleteRun(runId: string): void {
  writeRuns(listRuns().filter((e) => e.runId !== runId));
  // Best-effort cleanup of associated keys.
  for (const suffix of ["topic", "report", "report_path", "chapter_count", "pending"]) {
    try {
      localStorage.removeItem(`run:${runId}:${suffix}`);
    } catch {
      /* ignore */
    }
  }
}

export function subscribeRuns(listener: () => void): () => void {
  const onLocal = () => listener();
  const onStorage = (e: StorageEvent) => {
    if (e.key === KEY) listener();
  };
  window.addEventListener("runs_index_changed", onLocal);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener("runs_index_changed", onLocal);
    window.removeEventListener("storage", onStorage);
  };
}
