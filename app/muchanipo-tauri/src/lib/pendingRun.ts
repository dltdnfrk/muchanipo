export const PENDING_RUN_TTL_MS = 5 * 60 * 1000;

function pendingKey(runId: string): string {
  return `run:${runId}:pending`;
}

function pendingAtKey(runId: string): string {
  return `run:${runId}:pending_at`;
}

function sessionPendingKey(runId: string): string {
  return `run:${runId}:pending_session`;
}

export function markPendingRun(runId: string, now = Date.now()): void {
  const token = `${now}:${Math.random().toString(36).slice(2, 10)}`;
  localStorage.setItem(pendingKey(runId), token);
  localStorage.setItem(pendingAtKey(runId), String(now));
  sessionStorage.setItem(sessionPendingKey(runId), token);
}

export function clearPendingRun(runId: string): void {
  localStorage.removeItem(pendingKey(runId));
  localStorage.removeItem(pendingAtKey(runId));
  sessionStorage.removeItem(sessionPendingKey(runId));
}

export function getPendingRunAutostartDecision(
  runId: string,
  now = Date.now(),
): { canStart: boolean; pending: boolean; reason?: string } {
  const token = localStorage.getItem(pendingKey(runId));
  if (!token) return { canStart: false, pending: false };

  const sessionToken = sessionStorage.getItem(sessionPendingKey(runId));
  if (!sessionToken || sessionToken !== token) {
    return { canStart: false, pending: true, reason: "session_mismatch" };
  }

  const createdAt = Number(localStorage.getItem(pendingAtKey(runId)));
  if (!Number.isFinite(createdAt) || now - createdAt > PENDING_RUN_TTL_MS) {
    return { canStart: false, pending: true, reason: "stale" };
  }

  return { canStart: true, pending: true };
}
