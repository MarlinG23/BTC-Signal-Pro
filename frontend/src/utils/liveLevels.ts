import { SignalType } from "./types";

export interface LiveLevels {
  tp: number;
  sl: number;
  rr: number;
}

/**
 * Live Entry/TP/SL distances — same ATR + floor + tier multipliers as the
 * signal card, so chart needles never disagree with the badge.
 */
export function computeLiveLevels(
  currentPrice: number,
  atr14: number | null,
  signalType: SignalType,
  tpMultiplier = 1,
  slMultiplier = 1
): LiveLevels | null {
  if (signalType === "HOLD") return null;

  const minTpDist = currentPrice * 0.005;
  const minSlDist = currentPrice * 0.003;
  const tpFromAtr = atr14 != null && atr14 > 0 ? atr14 * 2 : 0;
  const slFromAtr = atr14 != null && atr14 > 0 ? atr14 * 1 : 0;
  const tpDist = Math.max(tpFromAtr, minTpDist) * tpMultiplier;
  const slDist = Math.max(slFromAtr, minSlDist) * slMultiplier;

  const isLong = signalType === "BUY" || signalType === "STRONG_BUY";
  const tp = isLong ? currentPrice + tpDist : currentPrice - tpDist;
  const sl = isLong ? currentPrice - slDist : currentPrice + slDist;
  const rr = slDist > 0 ? tpDist / slDist : 0;

  return { tp, sl, rr };
}
