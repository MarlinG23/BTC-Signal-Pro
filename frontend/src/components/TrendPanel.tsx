/**
 * 4-hour trend panel — shows the higher-timeframe directional bias
 * used as a mandatory gate before 1M entry signals fire.
 */

import clsx from "clsx";
import { IndicatorSnapshot } from "../utils/types";
import { formatPrice, fmt } from "../utils/format";
import { useApi } from "../hooks/useApi";
import { deriveTrend } from "../utils/trend";

interface TrendPanelProps {
  /** 1-minute snapshot for ENTRY context */
  snapshot1m: IndicatorSnapshot | null;
}

interface Snapshot4H extends IndicatorSnapshot {
  candles_buffered?: number;
}

export function TrendPanel({ snapshot1m }: TrendPanelProps) {
  const { data: snap4h, loading } = useApi<Snapshot4H>(
    "/api/indicators/4h",
    60_000 // refresh every minute — 4H candles don't change that fast
  );

  const trend = deriveTrend(snap4h);

  const rows: { label: string; val1m: string | null; val4h: string | null }[] = [
    {
      label: "EMA 20",
      val1m: snapshot1m?.ema_20 != null ? formatPrice(snapshot1m.ema_20) : null,
      val4h: snap4h?.ema_20 != null ? formatPrice(snap4h.ema_20) : null,
    },
    {
      label: "EMA 50",
      val1m: snapshot1m?.ema_50 != null ? formatPrice(snapshot1m.ema_50) : null,
      val4h: snap4h?.ema_50 != null ? formatPrice(snap4h.ema_50) : null,
    },
    {
      label: "EMA 200",
      val1m: snapshot1m?.ema_200 != null ? formatPrice(snapshot1m.ema_200) : null,
      val4h: snap4h?.ema_200 != null ? formatPrice(snap4h.ema_200) : null,
    },
    {
      label: "RSI (14)",
      val1m: snapshot1m?.rsi_14 != null ? fmt(snapshot1m.rsi_14, 1) : null,
      val4h: snap4h?.rsi_14 != null ? fmt(snap4h.rsi_14, 1) : null,
    },
    {
      label: "MACD Line",
      val1m: snapshot1m?.macd_line != null ? fmt(snapshot1m.macd_line, 2) : null,
      val4h: snap4h?.macd_line != null ? fmt(snap4h.macd_line, 2) : null,
    },
  ];

  return (
    <div className="card">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-sm font-semibold text-brand-muted uppercase tracking-wider">
            Multi-Timeframe Analysis
          </h2>
          <p className="text-xs text-brand-muted mt-0.5">
            Signals only fire when TREND + ENTRY agree
          </p>
        </div>
        {/* 4H trend badge */}
        <div className="text-right">
          <div
            className={clsx(
              "text-base font-bold tracking-wide",
              trend.color
            )}
          >
            {loading ? "…" : trend.label}
          </div>
          <div className="text-xs text-brand-muted">4H TREND</div>
        </div>
      </div>

      {/* Comparison table */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-brand-muted uppercase tracking-wider border-b border-brand-border">
              <th className="text-left pb-2 pr-4">Indicator</th>
              <th className="text-right pb-2 pr-4">
                <span className="text-yellow-400">ENTRY</span> 1m
              </th>
              <th className="text-right pb-2">
                <span className={trend.color}>TREND</span> 4H
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ label, val1m, val4h }) => (
              <tr
                key={label}
                className="border-b border-brand-border/40 last:border-0"
              >
                <td className="py-1.5 pr-4 text-brand-muted">{label}</td>
                <td className="text-right pr-4 font-mono text-white">
                  {val1m ?? <span className="text-brand-muted">—</span>}
                </td>
                <td className="text-right font-mono text-white">
                  {val4h ?? <span className="text-brand-muted">—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Filter status pills */}
      <div className="flex gap-2 mt-4 flex-wrap">
        <div
          className={clsx(
            "text-xs px-2 py-1 rounded border",
            trend.direction === 1
              ? "border-emerald-500/50 text-emerald-400 bg-emerald-900/20"
              : trend.direction === -1
              ? "border-red-500/50 text-red-400 bg-red-900/20"
              : "border-brand-border text-brand-muted"
          )}
        >
          4H: {trend.label}
        </div>
        <div className="text-xs px-2 py-1 rounded border border-brand-border text-brand-muted">
          BUY gate: F&amp;G &lt; 40
        </div>
        <div className="text-xs px-2 py-1 rounded border border-brand-border text-brand-muted">
          SELL gate: F&amp;G &gt; 60
        </div>
        {snap4h?.candles_buffered != null && (
          <div className="text-xs px-2 py-1 rounded border border-brand-border text-brand-muted ml-auto">
            {snap4h.candles_buffered} × 4H candles
          </div>
        )}
      </div>
    </div>
  );
}
