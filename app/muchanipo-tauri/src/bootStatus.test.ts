import { describe, expect, it } from "vitest";
import {
  type MuchanipoBootState,
  markMuchanipoBoot,
  markMuchanipoMountedIfStillStarting,
  readMuchanipoBootStatus,
} from "./bootStatus";

function fakeRoot(initial = "static-fallback") {
  return {
    dataset: { muchanipoBoot: initial, muchanipoBootMessage: "" },
  } as unknown as HTMLElement;
}

describe("Muchanipo boot status observability", () => {
  it("keeps the static HTML shell and pre-React error states in the typed taxonomy", () => {
    const states: MuchanipoBootState[] = ["html-shell", "window-error", "window-rejection"];

    for (const state of states) {
      const root = fakeRoot(state);
      expect(readMuchanipoBootStatus(root).state).toBe(state);
    }
  });

  it("records boot states and diagnostic messages on the root dataset", () => {
    const root = fakeRoot();

    markMuchanipoBoot(root, "react-starting");
    expect(readMuchanipoBootStatus(root)).toEqual({ state: "react-starting", message: "" });

    markMuchanipoBoot(root, "react-error", new Error("render failed"));
    expect(readMuchanipoBootStatus(root)).toEqual({ state: "react-error", message: "render failed" });
  });

  it("only marks mounted while React is still starting", () => {
    const starting = fakeRoot("react-starting");
    markMuchanipoMountedIfStillStarting(starting);
    expect(readMuchanipoBootStatus(starting).state).toBe("react-mounted");

    const errored = fakeRoot("react-error");
    markMuchanipoMountedIfStillStarting(errored);
    expect(readMuchanipoBootStatus(errored).state).toBe("react-error");
  });
});
