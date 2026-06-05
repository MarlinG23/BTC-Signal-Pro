/**
 * Table of historical signals with outcome tracking.
 */

import clsx from "clsx";
import { Signal, SignalType } from "../utils/types";
import { formatPrice, fmt, timeAgo } from "../utils/format";

interface SignalHistoryProps {
  signals: Signal[];
  loading?: boolean;
}

const TYPE_STYLES: Record<SignalType, string> = {
  STRONG_BUY: "badge-strong-buy",
  BUY: "badge-buy",
  HOLD: "badge-hold",
  SELL: "badge-sell",
  STRONG_SELL: "badge-strong-sell",
};

export function SignalHistory({ signals, loading }: SignalHistoryProps) {
  return (
    <div className="card">
      <h2 className="text-sm font-semibold text-brand-muted uppercase tracking-wider mb-4">
        Signal History
      </h2>

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
