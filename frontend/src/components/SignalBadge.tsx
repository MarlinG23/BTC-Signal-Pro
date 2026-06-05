/**
 * Prominent animated signal badge displayed at the top of the dashboard.
 * Changes color and animation based on the current signal type.
 */

import clsx from "clsx";
import { SignalType } from "../utils/types";
import { formatPrice, fmt } from "../utils/format";
import { Signal } from "../utils/types";

interface SignalBadgeProps {
  signal: Signal | null;
}

const SIGNAL_CONFIG: Record<
  SignalType,
  { label: string; colorClass: string; glowClass: string; emoji: string }
> = {
  STRONG_BUY: {
    label: "STRONG BUY",
    colorClass: "text-emerald-400 border-emerald-500",
    glowClass: "shadow-[0_0_30px_rgba(16,185,129,0.4)]",
    emoji: "🚀",
  },
  BUY: {
    label: "BUY",
    colorClass: "text-green-400 border-green-500",
    glowClass: "shadow-[0_0_20px_rgba(34,197,94,0.3)]",
    emoji: "📈",
  },
  HOLD: {
    label: "HOLD",
    colorClass: "text-yellow-400 border-yellow-500",
    glowClass: "",
    emoji: "⏸️",
  },
  SELL: {
    label: "SELL",
    colorClass: "text-orange-400 border-orange-500",
    glowClass: "shadow-[0_0_20px_rgba(251,146,60,0.3)]",
    emoji: "📉",
  },
  STRONG_SELL: {
    label: "STRONG SELL",
    colorClass: "text-red-400 border-red-500",
    glowClass: "shadow-[0_0_30px_rgba(239,68,68,0.4)]",
    emoji: "💥",
  },
};

export function SignalBadge({ signal }: SignalBadgeProps) {
  if (!signal) {
    return (
      <div className="card flex flex-col items-center justify-center py-8 gap-2">
        <div className="text-4xl">📊</div>
        <p className="text-brand-muted text-sm">Waiting for signal…</p>
        <p className="text-brand-muted text-xs">Warming up indicators</p>
      </div>
    );
  }

  const config = SIGNAL_CONFIG[signal.signal_type];
  const isActionable =
    signal.signal_type !== "HOLD" && signal.signal_type !== null;

  return (
    <div
      className={clsx(
        "card flex flex-col items-center gap-3 py-6 border-2 transition-all duration-500 animate-slide-in",
        config.colorClass,
        config.glowClass,
        isActionable && "animate-pulse_slow"
      )}
    >
      {/* Main badge */}
      <div className="flex items-center gap-3">
        <span className="text-4xl">{config.emoji}</span>
        <div className="text-center">
          <div className={clsx("text-3xl font-bold tracking-widest", config.colorClass)}>
            {config.label}
          </div>
          <div className="text-brand-muted text-sm mt-1">
            {signal.confidence.toFixed(1)}% confidence · {signal.indicators_agreed} indicators agreed
          </div>
        </div>
      </div>

      {/* Price levels */}
      {signal.signal_type !== "HOLD" && (
        <div className="grid grid-cols-3 gap-4 w-full mt-2 text-center">
          <div>
            <p className="text-brand-muted text-xs uppercase tracking-wider">Entry</p>
            <p className="text-white font-semibold">{formatPrice(signal.entry_price)}</p>
          </div>
          <div>
            <p className="text-emerald-400 text-xs uppercase tracking-wider">Take Profit</p>
            <p className="text-emerald-400 font-semibold">
              {signal.take_profit ? formatPrice(signal.take_profit) : "—"}
            </p>
          </div>
          <div>
            <p className="text-red-400 text-xs uppercase tracking-wider">Stop Loss</p>
            <p className="text-red-400 font-semibold">
              {signal.stop_loss ? formatPrice(signal.stop_loss) : "—"}
            </p>
          </div>
        </div>
      )}

      {/* Risk/Reward */}
      {signal.risk_reward_ratio && (
        <div className="text-brand-muted text-sm">
          R:R = <span className="text-brand-blue">{fmt(signal.risk_reward_ratio, 2)}:1</span>
        </div>
      )}
    </div>
  );
}
