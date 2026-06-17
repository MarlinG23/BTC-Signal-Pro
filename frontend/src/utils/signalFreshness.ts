import { parseISO } from "date-fns";

/** Signals older than this are treated as stale and shown as HOLD. */
export const SIGNAL_FRESH_MS = 5 * 60 * 1000;

export function isSignalFresh(
  generatedAt: string | null | undefined,
  nowMs: number = Date.now()
): boolean {
  if (!generatedAt) return false;
  try {
    const ageMs = nowMs - parseISO(generatedAt).getTime();
    return ageMs >= 0 && ageMs <= SIGNAL_FRESH_MS;
  } catch {
    return false;
  }
}
