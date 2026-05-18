export type MuchanipoBootState =
  | "html-shell"
  | "static-fallback"
  | "react-starting"
  | "react-mounted"
  | "missing-root"
  | "react-error"
  | "window-error"
  | "window-rejection";

export interface MuchanipoBootStatus {
  state: MuchanipoBootState;
  message: string;
}

const BOOT_STATE_KEY = "muchanipoBoot";
const BOOT_MESSAGE_KEY = "muchanipoBootMessage";

function errorMessage(error?: unknown): string {
  if (!error) return "";
  if (error instanceof Error) return error.message;
  return String(error);
}

export function readMuchanipoBootStatus(root: HTMLElement): MuchanipoBootStatus {
  return {
    state: (root.dataset[BOOT_STATE_KEY] as MuchanipoBootState | undefined) || "static-fallback",
    message: root.dataset[BOOT_MESSAGE_KEY] || "",
  };
}

export function markMuchanipoBoot(
  root: HTMLElement,
  state: MuchanipoBootState,
  error?: unknown,
): MuchanipoBootStatus {
  const message = errorMessage(error);
  root.dataset[BOOT_STATE_KEY] = state;
  root.dataset[BOOT_MESSAGE_KEY] = message;
  return { state, message };
}

export function markMuchanipoMountedIfStillStarting(root: HTMLElement) {
  if (readMuchanipoBootStatus(root).state === "react-starting") {
    markMuchanipoBoot(root, "react-mounted");
  }
}
