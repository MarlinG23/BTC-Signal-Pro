/**
 * Table of historical signals with outcome tracking and win rate badge.
 */

import clsx from "clsx";
import { Signal, SignalType } from "../utils/types";
import { formatPrice, fmt, timeAgo } from "../utils/format";
import { useApi } from "../hooks/useApi";

interface SignalHistoryProps {
  signals: Signal[];
  loading?: boolean;
}

interface SignalStats {
  wins: number;
  losses: number;
  open: number;
  win_rate_pct: number;
  avg_pnl_pct: number;
}

const TYPE_STYLES: Record<SignalType, string> = {
  STRONG_BUY: "badge-strong-buy",
  BUY: "badge-buy",
  HOLD: "badge-hold",
  SELL: "badge-sell",
  STRONG_SELL: "badge-strong-sell",
};

const OUTCOME_STYLES: Record<string, string> = {
  WIN: "text-emerald-400 font-semibold",
  LOSS: "text-red-400 font-semibold",
  OPEN: "text-brand-muted",
};

export function SignalHistory({ signals, loading }: SignalHistoryProps) {
  const { data: stats } = useApi<SignalStats>("/api/signals/stats", 60_000);

  const decided = (stats?.wins ?? 0) + (stats?.losses ?? 0);

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-brand-muted uppercase tracking-wider">
          Signal History
        </h2>

        {/* Win rate badge — only shown once signals have been resolved */}
        {decided > 0 && stats && (
          <div className="flex items-center gap-3 text-xs">
            <span
              className={clsx(
                "px-2 py-1 rounded font-semibold",
                stats.win_rate_pct >= 60
                  ? "bg-emerald-900/50 text-emerald-400"
                  : stats.win_rate_pct >= 40
                  ? "bg-yellow-900/50 text-yellow-400"
                  : "bg-red-900/50 text-red-400"
              )}
            >
              WIN RATE {stats.win_rate_pct}%
            </span>
            <span className="text-brand-muted">
              {stats.wins}W / {stats.losses}L
              {stats.avg_pnl_pct !== 0 && (
                <span
                  className={clsx(
                    "ml-2",
                    stats.avg_pnl_pct > 0 ? "text-emerald-400" : "text-red-400"
                  )}
                >
                  avg {stats.avg_pnl_pct > 0 ? "+" : ""}
                  {stats.avg_pnl_pct.toFixed(2)}%
                </span>
              )}
            </span>
          </div>
        )}
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-6 text-brand-muted text-sm">
          Loading…
        </div>
      ) : signals.length === 0 ? (
        <div className="flex items-center justify-center py-6 text-brand-muted text-sm">
          No signals fired yet
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-brand-muted text-xs uppercase tracking-wider border-b border-brand-border">
                <th className="text-left pb-2 pr-4">Signal</th>
                <th className="text-right pb-2 pr-4">Conf%</th>
                <th className="text-right pb-2 pr-4">Entry</th>
                <th className="text-right pb-2 pr-4">TP</th>
                <th className="text-right pb-2 pr-4">SL</th>
                <th className="text-right pb-2 pr-4">R:R</th>
                <th className="text-right pb-2 pr-4">Outcome</th>
                <th className="text-right pb-2">Time</th>
              </tr>
            </thead>
            <tbody>
              {signals.map((s) => (
                <tr
                  key={s.id}
                  className="border-b border-brand-border/50 last:border-0 hover:bg-brand-border/20 transition-colors"
                >
                  <td className="py-2 pr-4">
                    <span
                      className={clsx(
                        "text-xs font-medium rounded px-2 py-1 border",
                        TYPE_STYLES[s.signal_type]
                      )}
                    >
                      {s.signal_type.replace("_", " ")}
                    </span>
                  </td>
                  <td className="text-right pr-4 font-mono">
                    {s.confidence.toFixed(1)}%
                  </td>
                  <td className="text-right pr-4 font-mono text-white">
                    {formatPrice(s.entry_price)}
                  </td>
                  <td className="text-right pr-4 font-mono text-emerald-400">
                    {s.take_profit ? formatPrice(s.take_profit) : "—"}
                  </td>
                  <td className="text-right pr-4 font-mono text-red-400">
                    {s.stop_loss ? formatPrice(s.stop_loss) : "—"}
                  </td>
                  <td className="text-right pr-4 font-mono text-brand-blue">
                    {s.risk_reward_ratio ? `${fmt(s.risk_reward_ratio, 2)}:1` : "—"}
                  </td>
                  <td className="text-right pr-4">
                    {s.outcome ? (
                      <span className={clsx("text-xs", OUTCOME_STYLES[s.outcome] ?? "text-brand-muted")}>
                        {s.outcome}
                        {s.pnl_percent != null && (
                          <span className="ml-1 font-mono">
                            ({s.pnl_percent > 0 ? "+" : ""}{s.pnl_percent.toFixed(2)}%)
                          </span>
                        )}
                      </span>
                    ) : (
                      <span className="text-xs text-brand-muted">pending</span>
                    )}
                  </td>
                  <td className="text-right text-brand-muted text-xs whitespace-nowrap">
                    {timeAgo(s.generated_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
