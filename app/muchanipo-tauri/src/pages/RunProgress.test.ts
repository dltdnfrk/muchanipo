import { describe, expect, it } from "vitest";
import { deriveLiveE2eStatus, parseEventBoolean } from "./RunProgress";

describe("deriveLiveE2eStatus", () => {
  it("proves live e2e when runtime status matches the current app run", () => {
    expect(
      deriveLiveE2eStatus({
        runId: "run-current",
        runtimeRunId: "run-current",
        runtimeHeartbeatStage: "interview",
        hasVisibleBackendHeartbeat: false,
      }),
    ).toBe("Backend run signals observed");
  });

  it("proves live e2e from visible heartbeat when runtime polling has not refreshed app_run_id yet", () => {
    expect(
      deriveLiveE2eStatus({
        runId: "run-current",
        runtimeRunId: undefined,
        runtimeHeartbeatStage: "interview",
        hasVisibleBackendHeartbeat: true,
      }),
    ).toBe("Backend run signals observed");
  });

  it("does not prove live e2e for a stale runtime without visible heartbeat", () => {
    expect(
      deriveLiveE2eStatus({
        runId: "run-current",
        runtimeRunId: "run-old",
        runtimeHeartbeatStage: "interview",
        hasVisibleBackendHeartbeat: false,
      }),
    ).toBe("Not proven in this UI session");
  });
});

describe("parseEventBoolean", () => {
  it("does not treat the string false as truthy", () => {
    expect(parseEventBoolean(false)).toBe(false);
    expect(parseEventBoolean("false")).toBe(false);
    expect(parseEventBoolean("0")).toBe(false);
    expect(parseEventBoolean("no")).toBe(false);
    expect(parseEventBoolean(true)).toBe(true);
    expect(parseEventBoolean("true")).toBe(true);
    expect(parseEventBoolean("1")).toBe(true);
    expect(parseEventBoolean("yes")).toBe(true);
  });
});
