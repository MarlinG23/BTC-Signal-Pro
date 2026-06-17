import { Signal, SignalType } from "./types";
import { TrendLabel } from "./trend";
import { isSignalFresh } from "./signalFreshness";

export type DisplaySignalType = "BUY" | "SELL" | "WAIT" | "HOLD";

export const MIN_SIGNAL_CONFIDENCE = 70;

export function is1mBullish(type: SignalType): boolean {
  return type === "BUY" || type === "STRONG_BUY";
}

export function is1mBearish(type: SignalType): boolean {
  return type === "SELL" || type === "STRONG_SELL";
}

export function resolveDisplayState(
  signal: Signal | null,
  trend4h: TrendLabel,
  nowMs: number = Date.now()
): DisplaySignalType {
  if (!signal || !isSignalFresh(signal.generated_at, nowMs)) {
    return "HOLD";
  }

  if (
    signal.signal_type === "HOLD" ||
    signal.confidence < MIN_SIGNAL_CONFIDENCE
  ) {
    return "HOLD";
  }

  const bullish1m = is1mBullish(signal.signal_type);
  const bearish1m = is1mBearish(signal.signal_type);

  if (!bullish1m && !bearish1m) {
    return "HOLD";
  }

  if (trend4h === "NEUTRAL" || trend4h === "LOADING") {
    return "WAIT";
  }

  if (trend4h === "BULLISH" && bullish1m) {
    return "BUY";
  }

  if (trend4h === "BEARISH" && bearish1m) {
    return "SELL";
  }

  return "WAIT";
}

/** Map display state to long/short for TP/SL recalculation. */
export function displayToLevelType(
  display: DisplaySignalType,
  rawType: SignalType
): SignalType {
  if (display === "BUY") return "BUY";
  if (display === "SELL") return "SELL";
  if (display === "WAIT") {
    return is1mBullish(rawType) ? "BUY" : is1mBearish(rawType) ? "SELL" : "HOLD";
  }
  return "HOLD";
}

export type TradeReadyStatus = "ready" | "waiting_4h" | "not_met";

function fearGreedAllows(
  display: DisplaySignalType,
  fearGreed: number | null
): boolean {
  if (fearGreed == null) return true;
  if (display === "BUY") return fearGreed < 40;
  if (display === "SELL") return fearGreed > 60;
  return false;
}

/** Evaluate whether all four trade conditions are satisfied. */
export function resolveTradeReadyStatus(
  signal: Signal | null,
  trend4h: TrendLabel,
  fearGreed: number | null,
  nowMs: number = Date.now()
): TradeReadyStatus {
  const display = resolveDisplayState(signal, trend4h, nowMs);

  if (
    display === "WAIT" &&
    (trend4h === "NEUTRAL" || trend4h === "LOADING")
  ) {
    return "waiting_4h";
  }

  if (display === "BUY" || display === "SELL") {
    const fresh = signal != null && isSignalFresh(signal.generated_at, nowMs);
    const confident =
      signal != null && signal.confidence >= MIN_SIGNAL_CONFIDENCE;
    const fgOk = fearGreedAllows(display, fearGreed);

    if (fresh && confident && fgOk) {
      return "ready";
    }
  }

  return "not_met";
}
