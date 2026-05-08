import { describe, expect, it, beforeEach, vi } from "vitest";
import {
  listRuns,
  pushRun,
  deleteRun,
  type RunIndexEntry,
} from "./runsIndex";

const KEY = "runs_index";

function makeStorage(): Storage {
  const store = new Map<string, string>();
  return {
    getItem(key: string): string | null {
      return store.has(key) ? (store.get(key) as string) : null;
    },
    setItem(key: string, value: string): void {
      store.set(key, String(value));
    },
    removeItem(key: string): void {
      store.delete(key);
    },
    clear(): void {
      store.clear();
    },
    get length(): number {
      return store.size;
    },
    key(index: number): string | null {
      return Array.from(store.keys())[index] ?? null;
    },
  } as Storage;
}

let testStorage: Storage;

beforeEach(() => {
  testStorage = makeStorage();
  vi.stubGlobal("localStorage", testStorage);
  vi.stubGlobal("sessionStorage", makeStorage());
  vi.stubGlobal("window", {
    dispatchEvent: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  });
});

function seed(entries: RunIndexEntry[]): void {
  testStorage.setItem(KEY, JSON.stringify(entries));
}

function clear(): void {
  testStorage.removeItem(KEY);
  for (let i = testStorage.length - 1; i >= 0; i--) {
    const k = testStorage.key(i);
    if (k?.startsWith("run:")) testStorage.removeItem(k);
  }
}

describe("runsIndex", () => {
  beforeEach(() => clear());

  describe("pushRun", () => {
    it("persists basic run entry", () => {
      pushRun("r-1", "topic A");
      const runs = listRuns();
      expect(runs).toHaveLength(1);
      expect(runs[0].runId).toBe("r-1");
      expect(runs[0].topic).toBe("topic A");
      expect(runs[0].status).toBe("running");
    });

    it("persists studio metadata when provided", () => {
      pushRun("r-2", "topic B", { studioId: "studio-42", studioModel: "sonnet-4.5" });
      const runs = listRuns();
      expect(runs[0].studioId).toBe("studio-42");
      expect(runs[0].studioModel).toBe("sonnet-4.5");
    });

    it("omits studio fields when not provided", () => {
      pushRun("r-3", "topic C");
      const runs = listRuns();
      expect(runs[0].studioId).toBeUndefined();
      expect(runs[0].studioModel).toBeUndefined();
    });

    it("deduplicates by runId and moves to front", () => {
      seed([
        { runId: "r-old", topic: "old", createdAt: 1, status: "done" },
      ]);
      pushRun("r-old", "updated", { studioId: "s-1" });
      const runs = listRuns();
      expect(runs).toHaveLength(1);
      expect(runs[0].topic).toBe("updated");
      expect(runs[0].studioId).toBe("s-1");
    });
  });

  describe("deleteRun", () => {
    it("removes run from index", () => {
      seed([
        { runId: "r-1", topic: "a", createdAt: 1, status: "running" },
        { runId: "r-2", topic: "b", createdAt: 2, status: "done" },
      ]);
      deleteRun("r-1");
      expect(listRuns()).toHaveLength(1);
      expect(listRuns()[0].runId).toBe("r-2");
    });

    it("cleans up all run-local keys including studio and discovery", () => {
      const runId = "r-cleanup";
      const keys = [
        `run:${runId}:topic`,
        `run:${runId}:report`,
        `run:${runId}:report_path`,
        `run:${runId}:chapter_count`,
        `run:${runId}:pending`,
        `run:${runId}:pending_at`,
        `run:${runId}:studioBrief`,
        `run:${runId}:studioModel`,
        `run:${runId}:studioId`,
        `run:${runId}:gaps`,
        `run:${runId}:sources`,
      ];
      for (const k of keys) localStorage.setItem(k, "x");
      seed([{ runId, topic: "t", createdAt: 1, status: "running" }]);

      deleteRun(runId);

      for (const k of keys) {
        expect(localStorage.getItem(k)).toBeNull();
      }
    });
  });

  describe("listRuns backward compatibility", () => {
    it("tolerates missing optional fields in stored JSON", () => {
      localStorage.setItem(
        KEY,
        JSON.stringify([
          { runId: "r-legacy", topic: "legacy", createdAt: 1, status: "done" },
        ]),
      );
      const runs = listRuns();
      expect(runs[0].studioId).toBeUndefined();
      expect(runs[0].studioModel).toBeUndefined();
    });
  });
});
