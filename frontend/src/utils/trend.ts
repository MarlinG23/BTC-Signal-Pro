import { IndicatorSnapshot } from "./types";

export type TrendLabel = "BULLISH" | "BEARISH" | "NEUTRAL" | "LOADING";

export function deriveTrend(snap: IndicatorSnapshot | null): {
  direction: 1 | -1 | 0;
  label: TrendLabel;
  color: string;
} {
  if (
    !snap ||
    snap.close_price == null ||
    snap.ema_20 == null ||
    snap.ema_50 == null
  ) {
    return { direction: 0, label: "LOADING", color: "text-brand-muted" };
  }

  const { close_price: p, ema_20: e20, ema_50: e50, rsi_14: rsi } = snap;

  if (p > e20 && e20 > e50 && (rsi == null || rsi < 70)) {
    return { direction: 1, label: "BULLISH", color: "text-emerald-400" };
  }
  if (p < e20 && e20 < e50 && (rsi == null || rsi > 30)) {
    return { direction: -1, label: "BEARISH", color: "text-red-400" };
  }
  return { direction: 0, label: "NEUTRAL", color: "text-yellow-400" };
}
