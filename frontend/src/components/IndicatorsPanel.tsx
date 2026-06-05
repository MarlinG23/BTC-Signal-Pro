/**
 * Panel displaying all technical indicator values in a grid layout.
 * Color-codes values based on their bullish/bearish implication.
 */

import clsx from "clsx";
import { IndicatorSnapshot } from "../utils/types";
import { fmt, formatPrice } from "../utils/format";

interface IndicatorsPanelProps {
  snapshot: IndicatorSnapshot | null;
}

interface IndicatorRowProps {
  label: string;
  value: string;
  status?: "bullish" | "bearish" | "neutral" | "none";
  subLabel?: string;
}

function IndicatorRow({ label, value, status = "none", subLabel }: IndicatorRowProps) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-brand-border last:border-0">
      <div>
        <span className="text-brand-muted text-sm">{label}</span>
        {subLabel && <p className="text-brand-muted text-xs">{subLabel}</p>}
      </div>
      <span
        className={clsx("font-mono text-sm font-medium", {
          "text-emerald-400": status === "bullish",
          "text-red-400": status === "bearish",
          "text-yellow-400": status === "neutral",
          "text-white": status === "none",
        })}
      >
        {value}
      </span>
    </div>
  );
}

function rsiStatus(rsi: number | null): "bullish" | "bearish" | "neutral" {
  if (rsi == null) return "neutral";
  if (rsi < 35) return "bullish";
  if (rsi > 65) return "bearish";
  return "neutral";
}

function macdStatus(line: number | null, signal: number | null): "bullish" | "bearish" | "neutral" {
  if (line == null || signal == null) return "neutral";
  if (line > signal) return "bullish";
  if (line < signal) return "bearish";
  return "neutral";
}

function emaStatus(
  close: number | null,
  ema20: number | null,
  ema50: number | null,
  ema200: number | null
): "bullish" | "bearish" | "neutral" {
  if (!close || !ema20 || !ema50) return "neutral";
  const aboveShort = close > ema20 && ema20 > ema50;
  const belowShort = close < ema20 && ema20 < ema50;
  if (aboveShort && (!ema200 || ema50 > ema200)) return "bullish";
  if (belowShort && (!ema200 || ema50 < ema200)) return "bearish";
  return "neutral";
}

function bbStatus(pctB: number | null): "bullish" | "bearish" | "neutral" {
  if (pctB == null) return "neutral";
  if (pctB < 0.2) return "bullish";
  if (pctB > 0.8) return "bearish";
  return "neutral";
}

export function IndicatorsPanel({ snapshot }: IndicatorsPanelProps) {
  if (!snapshot) {
    return (
      <div className="card">
        <h2 className="text-sm font-semibold text-brand-muted uppercase tracking-wider mb-4">
          Technical Indicators
        </h2>
        <div className="flex items-center justify-center py-8 text-brand-muted text-sm">
          Warming up… (need 200 candles for EMA-200)
        </div>
      </div>
    );
  }

  const s = snapshot;

  return (
    <div className="card">
      <h2 className="text-sm font-semibold text-brand-muted uppercase tracking-wider mb-3">
        Technical Indicators
      </h2>

      {/* RSI */}
      <div className="mb-3">
        <p className="text-xs text-brand-muted uppercase tracking-wider mb-1">Momentum</p>
        <IndicatorRow
          label="RSI (14)"
          value={fmt(s.rsi_14, 1)}
          status={rsiStatus(s.rsi_14)}
          subLabel={
            s.rsi_14
              ? s.rsi_14 < 35
                ? "Oversold"
                : s.rsi_14 > 65
                ? "Overbought"
                : "Neutral"
              : undefined
          }
        />
      </div>

      {/* MACD */}
      <div className="mb-3">
        <p className="text-xs text-brand-muted uppercase tracking-wider mb-1">MACD (12,26,9)</p>
        <IndicatorRow
          label="MACD Line"
          value={fmt(s.macd_line)}
          status={macdStatus(s.macd_line, s.macd_signal)}
        />
        <IndicatorRow label="Signal Line" value={fmt(s.macd_signal)} />
        <IndicatorRow
          label="Histogram"
          value={fmt(s.macd_histogram)}
          status={
            s.macd_histogram == null
              ? "neutral"
              : s.macd_histogram > 0
              ? "bullish"
              : s.macd_histogram < 0
              ? "bearish"
              : "neutral"
          }
        />
      </div>

      {/* EMAs */}
      <div className="mb-3">
        <p className="text-xs text-brand-muted uppercase tracking-wider mb-1">Moving Averages</p>
        <IndicatorRow
          label="EMA 20"
          value={formatPrice(s.ema_20)}
          status={emaStatus(s.close_price, s.ema_20, s.ema_50, s.ema_200)}
        />
        <IndicatorRow label="EMA 50" value={formatPrice(s.ema_50)} />
        <IndicatorRow
          label="EMA 200"
          value={s.ema_200 ? formatPrice(s.ema_200) : "Warming up…"}
        />
      </div>

      {/* Bollinger Bands */}
      <div className="mb-3">
        <p className="text-xs text-brand-muted uppercase tracking-wider mb-1">
          Bollinger Bands (20,2)
        </p>
        <IndicatorRow label="Upper Band" value={formatPrice(s.bb_upper)} />
        <IndicatorRow label="Middle (SMA20)" value={formatPrice(s.bb_middle)} />
        <IndicatorRow label="Lower Band" value={formatPrice(s.bb_lower)} />
        <IndicatorRow
          label="%B Position"
          value={s.bb_percent_b != null ? (s.bb_percent_b * 100).toFixed(1) + "%" : "—"}
          status={bbStatus(s.bb_percent_b)}
          subLabel={
            s.bb_percent_b != null
              ? s.bb_percent_b < 0.2
                ? "Near lower band"
                : s.bb_percent_b > 0.8
                ? "Near upper band"
                : "Mid-band"
              : undefined
          }
        />
      </div>

      {/* Volume */}
      <div>
        <p className="text-xs text-brand-muted uppercase tracking-wider mb-1">Volume</p>
        <IndicatorRow label="Volume SMA 20" value={fmt(s.volume_sma_20, 2)} />
        <IndicatorRow
          label="Volume Ratio"
          value={s.volume_ratio != null ? s.volume_ratio.toFixed(2) + "x" : "—"}
          status={
            s.volume_ratio == null
              ? "neutral"
              : s.volume_ratio >= 1.5
              ? "bullish"
              : s.volume_ratio <= 0.5
              ? "bearish"
              : "neutral"
          }
          subLabel={
            s.volume_ratio != null
              ? s.volume_ratio >= 1.5
                ? "High volume"
                : s.volume_ratio <= 0.5
                ? "Low volume"
                : "Average volume"
              : undefined
          }
        />
      </div>
    </div>
  );
}
