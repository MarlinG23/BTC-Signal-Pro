import { TrendLabel } from "./trend";
import { WaitSignal } from "./types";
import { isSignalFresh } from "./signalFreshness";

export interface IdleReason {
  emoji: string;
  text: string;
  className: string;
}

/** Contextual idle / WAIT footer — replaces generic "Conditions not met". */
export function resolveIdleReason(
  trend4h: TrendLabel,
  fearGreed: number | null,
  waitSignal: WaitSignal | null,
  nowMs: number = Date.now()
): IdleReason {
  const freshWait =
    waitSignal != null && isSignalFresh(waitSignal.generated_at, nowMs);

  if (freshWait && waitSignal.block_reason) {
    return {
      emoji: "🟡",
      text: waitSignal.block_reason,
      className: "text-yellow-400",
    };
  }

  if (freshWait) {
    return {
      emoji: "⏳",
      text: "Entry ready, waiting for trend agreement",
      className: "text-yellow-400",
    };
  }

  const lines: string[] = [];

  if (trend4h === "BEARISH") {
    lines.push("4H bearish — looking for SELL entries");
  } else if (trend4h === "BULLISH") {
    lines.push("4H bullish — looking for BUY entries");
  } else if (trend4h === "NEUTRAL") {
    lines.push("4H mixed — waiting for EMA stack to confirm");
  }

  if (fearGreed != null && fearGreed > 60) {
    lines.push(`F&G ${fearGreed} greed (context only)`);
  } else if (fearGreed != null && fearGreed < 40) {
    lines.push(`F&G ${fearGreed} fear (context only)`);
  }

  if (lines.length > 0) {
    return {
      emoji: "ℹ️",
      text: lines.join(" · "),
      className: "text-brand-muted",
    };
  }

  return {
    emoji: "…",
    text: "Waiting for fresh entry signal…",
    className: "text-brand-muted",
  };
}
