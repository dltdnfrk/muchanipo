import { describe, expect, it } from "vitest";
import { formatStatus, progressCopy, stageSummary } from "./BrowserHome";

describe("BrowserHome run status model", () => {
  it("treats running runs as live investigation with heartbeat/source guidance", () => {
    const summary = stageSummary("running");

    expect(formatStatus("running")).toBe("진행");
    expect(progressCopy("running")).toBe("상세 화면에서 live step 확인");
    expect(summary.label).toBe("실시간 조사 진행 중");
    expect(summary.detail).toContain("heartbeat");
    expect(summary.detail).toContain("source event");
  });

  it("keeps failed runs inspectable instead of hiding the detail screen", () => {
    const summary = stageSummary("failed");

    expect(formatStatus("failed")).toBe("실패");
    expect(progressCopy("failed")).toBe("확인 필요");
    expect(summary.detail).toContain("마지막 backend event");
  });
});
