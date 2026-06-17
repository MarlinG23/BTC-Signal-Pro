/**
 * Prominent animated signal badge displayed at the top of the dashboard.
 * Changes color and animation based on the current signal type.
 */

import { useEffect, useState } from "react";
import clsx from "clsx";
import { Signal, SignalType } from "../utils/types";
import { formatPrice, fmt, timeAgoSeconds } from "../utils/format";
import { isSignalFresh } from "../utils/signalFreshness";

interface SignalBadgeProps {
  signal: Signal | null;
  /** Live BTC price from WebSocket — used for current entry and TP/SL. */
  currentPrice: number | null;
  /** Latest ATR(14) from 1M indicators for TP/SL recalculation. */
  atr14: number | null;
}

function computeLiveLevels(
  currentPrice: number,
  atr14: number | null,
  signalType: SignalType
): { tp: number; sl: number; rr: number } | null {
  if (signalType === "HOLD") return null;

  const minTpDist = currentPrice * 0.005;
  const minSlDist = currentPrice * 0.003;
  const tpFromAtr = atr14 != null && atr14 > 0 ? atr14 * 2 : 0;
  const slFromAtr = atr14 != null && atr14 > 0 ? atr14 * 1 : 0;
  const tpDist = Math.max(tpFromAtr, minTpDist);
  const slDist = Math.max(slFromAtr, minSlDist);

  const isLong = signalType === "BUY" || signalType === "STRONG_BUY";
  const tp = isLong ? currentPrice + tpDist : currentPrice - tpDist;
  const sl = isLong ? currentPrice - slDist : currentPrice + slDist;
  const rr = slDist > 0 ? tpDist / slDist : 0;

  return { tp, sl, rr };
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

export function SignalBadge({ signal, currentPrice, atr14 }: SignalBadgeProps) {
  const [, setTick] = useState(0);
  const fresh = signal != null && isSignalFresh(signal.generated_at);
  const activeSignal = fresh ? signal : null;

  useEffect(() => {
    if (!fresh) return;
    const id = window.setInterval(() => setTick((t) => t + 1), 1000);
    return () => window.clearInterval(id);
  }, [fresh, signal?.generated_at]);

  if (!activeSignal) {
    return (
      <div className="card flex flex-col items-center justify-center py-8 gap-2">
        <div className="text-4xl">📊</div>
        <p className="text-brand-muted text-sm">HOLD — no active signal</p>
        <p className="text-brand-muted text-xs">
          {signal && !fresh
            ? "Last signal expired (older than 5 minutes)"
            : "Waiting for fresh entry signal…"}
        </p>
      </div>
    );
  }

  const config = SIGNAL_CONFIG[activeSignal.signal_type];
  const isActionable =
    activeSignal.signal_type !== "HOLD" && activeSignal.signal_type !== null;

  const liveEntry = currentPrice ?? activeSignal.entry_price;
  const liveLevels =
    liveEntry != null
      ? computeLiveLevels(liveEntry, atr14, activeSignal.signal_type)
      : null;
  const displayTp = liveLevels?.tp ?? activeSignal.take_profit;
  const displaySl = liveLevels?.sl ?? activeSignal.stop_loss;
  const displayRr = liveLevels?.rr ?? activeSignal.risk_reward_ratio;
  const usingLivePrice =
    currentPrice != null && currentPrice !== activeSignal.entry_price;

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
            {activeSignal.confidence.toFixed(1)}% confidence · {activeSignal.indicators_agreed} indicators agreed
          </div>
        </div>
      </div>

      {/* Price levels — entry anchored to live price when available */}
      {activeSignal.signal_type !== "HOLD" && (
        <div className="w-full mt-2 space-y-2 text-center">
          <p className="text-brand-muted text-xs">
            Signal generated {timeAgoSeconds(activeSignal.generated_at)}
            {usingLivePrice && (
              <span className="block text-brand-muted/80">
                Original entry {formatPrice(activeSignal.entry_price)}
              </span>
            )}
          </p>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <p className="text-brand-muted text-xs uppercase tracking-wider">
                {usingLivePrice ? "Current Entry" : "Entry"}
              </p>
              <p className="text-white font-semibold">{formatPrice(liveEntry)}</p>
            </div>
            <div>
              <p className="text-emerald-400 text-xs uppercase tracking-wider">Take Profit</p>
              <p className="text-emerald-400 font-semibold">
                {displayTp != null ? formatPrice(displayTp) : "—"}
              </p>
            </div>
            <div>
              <p className="text-red-400 text-xs uppercase tracking-wider">Stop Loss</p>
              <p className="text-red-400 font-semibold">
                {displaySl != null ? formatPrice(displaySl) : "—"}
              </p>
            </div>
          </div>
          {displayTp != null && displaySl != null && (
            <p className="text-brand-muted text-xs">
              TP: {formatPrice(displayTp)} | SL: {formatPrice(displaySl)}
            </p>
          )}
        </div>
      )}

      {/* Risk/Reward */}
      {displayRr != null && displayRr > 0 && (
        <div className="text-brand-muted text-sm">
          R:R = <span className="text-brand-blue">{fmt(displayRr, 2)}:1</span>
        </div>
      )}
    </div>
  );
}
