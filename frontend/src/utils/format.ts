/**
 * Formatting utilities used across the dashboard.
 */

import { differenceInMinutes, formatDistanceToNow, parseISO } from "date-fns";

/** Format a number as a USD price with commas and up to 2 decimal places. */
export function formatPrice(value: number | null | undefined): string {
  if (value == null) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

/** Format a number as a percentage with a sign prefix. */
export function formatPct(
  value: number | null | undefined,
  decimals = 2
): string {
  if (value == null) return "—";
  const sign = value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(decimals)}%`;
}

/** Format a float to N decimal places, or return "—" for null. */
export function fmt(
  value: number | null | undefined,
  decimals = 2
): string {
  if (value == null) return "—";
  return value.toFixed(decimals);
}

/** Return a human-readable relative time (e.g. "3 minutes ago"). */
export function timeAgo(isoString: string | null | undefined): string {
  if (!isoString) return "—";
  try {
    return formatDistanceToNow(parseISO(isoString), { addSuffix: true });
  } catch {
    return "—";
  }
}

/** Relative freshness in minutes only (for Fear & Greed gauge). */
export function timeAgoMinutes(isoString: string | null | undefined): string {
  if (!isoString) return "—";
  try {
    const minutes = differenceInMinutes(new Date(), parseISO(isoString));
    if (minutes < 1) return "just now";
    return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  } catch {
    return "—";
  }
}

/** Convert a SignalType to a display-friendly label. */
export function signalLabel(type: string): string {
  return type.replace("_", " ");
}

/** Truncate a string to maxLen, appending "…" if truncated. */
export function truncate(str: string, maxLen = 80): string {
  return str.length > maxLen ? str.slice(0, maxLen - 1) + "…" : str;
}
