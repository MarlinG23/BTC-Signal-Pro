/**
 * Multi-timeframe confluence panel — shows the trend direction across
 * 15m/30m/1h/2h and how many agree with a hypothetical BUY or SELL right
 * now. Validated via backtest (30/60/90-day windows all positive) as an
 * additional filter layer on top of the 4H trend + Fear & Greed gates:
 * a signal only fires live if at least `min_agreement_required` of these
 * four timeframes agree with its direction.
 */

import clsx from "clsx";
import { useApi } from "../hooks/useApi";
import { MtfIndicatorsResponse } from "../utils/types";

const TIMEFRAME_ORDER = ["15m", "30m", "1h", "2h"];

function trendColor(trend: 1 | -1 | 0): string {
  if (trend === 1) return "text-emerald-400";
  if (trend === -1) return "text-red-400";
  return "text-brand-muted";
}

function trendBorder(trend: 1 | -1 | 0): string {
  if (trend === 1) return "border-emerald-500/50 bg-emerald-900/20";
  if (trend === -1) return "border-red-500/50 bg-red-900/20";
  return "border-brand-border";
}

export function MtfConfluencePanel() {
  const { data, loading } = useApi<MtfIndicatorsResponse>(
    "/api/indicators/mtf",
    60_000 // matches TrendPanel's 4H refresh cadence
  );

  const timeframes = data?.timeframes ?? {};
  const minRequired = data?.min_agreement_required ?? 1;
  const total = data?.total_timeframes ?? TIMEFRAME_ORDER.length;

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-sm font-semibold text-brand-muted uppercase tracking-wider">
            Confluence Filter
          </h2>
          <p className="text-xs text-brand-muted mt-0.5">
            Needs {minRequired}/{total} timeframes to agree before a signal fires
          </p>
        </div>
        {data && (
          <div className="flex gap-3 text-right">
            <div>
              <div className="text-sm font-bold text-emerald-400">
                {data.current_buy_agreement}/{total}
              </div>
              <div className="text-xs text-brand-muted">for BUY</div>
            </div>
            <div>
              <div className="text-sm font-bold text-red-400">
                {data.current_sell_agreement}/{total}
              </div>
              <div className="text-xs text-brand-muted">for SELL</div>
            </div>
          </div>
        )}
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {TIMEFRAME_ORDER.map((tf) => {
          const snap = timeframes[tf];
          const trend = snap?.trend ?? 0;
          return (
            <div
              key={tf}
              className={clsx(
                "rounded border px-2 py-2 text-center",
                trendBorder(trend)
              )}
            >
              <div className="text-xs text-brand-muted uppercase">{tf}</div>
              <div className={clsx("text-sm font-bold", trendColor(trend))}>
                {loading && !snap ? "…" : snap?.trend_label ?? "NEUTRAL"}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
