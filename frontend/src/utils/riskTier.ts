/** 4H RSI risk tiers — mirrors backend/signals/risk_tier.py */

export interface RiskTier {
  tier: 1 | 2 | 3;
  sizeMultiplier: number;
  tpMultiplier: number;
  slMultiplier: number;
}

export function getRiskTier(rsi4h: number | null | undefined): RiskTier {
  if (rsi4h == null || rsi4h < 70) {
    return { tier: 1, sizeMultiplier: 1, tpMultiplier: 1, slMultiplier: 1 };
  }
  if (rsi4h < 85) {
    return { tier: 2, sizeMultiplier: 0.5, tpMultiplier: 0.6, slMultiplier: 0.7 };
  }
  return { tier: 3, sizeMultiplier: 0.25, tpMultiplier: 0.4, slMultiplier: 0.5 };
}

export function formatOutcome(outcome: string | null | undefined): string {
  if (outcome === "WIN") return "TP hit";
  if (outcome === "LOSS") return "SL hit";
  if (outcome === "OPEN") return "still open";
  return "still open";
}

export function tierHeadline(tier: number, rsi4h: number | null | undefined): string {
  const rsi =
    rsi4h != null && Number.isFinite(rsi4h) ? `RSI ${rsi4h.toFixed(1)}` : "RSI n/a";
  if (tier === 3) return `Tier 3 (Extended: ${rsi})`;
  if (tier === 2) return `Tier 2 (Elevated: ${rsi})`;
  return `Tier 1 (Standard: ${rsi})`;
}

export function tierSizeHint(sizeMultiplier: number | null | undefined): string {
  const pct = Math.round((sizeMultiplier ?? 1) * 100);
  if (pct >= 100) return "Full size 100%, normal TP/SL";
  return `Reduced size ${pct}%, tightened TP/SL`;
}
