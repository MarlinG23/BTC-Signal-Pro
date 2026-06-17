/**
 * Prominent animated signal badge displayed at the top of the dashboard.
 * Shows BUY/SELL only when 1M and 4H agree; WAIT when 4H is neutral.
 */

import { useEffect, useState } from "react";
import clsx from "clsx";
import { Signal, SignalType } from "../utils/types";
import { formatPrice, fmt, timeAgoSeconds } from "../utils/format";
import { isSignalFresh } from "../utils/signalFreshness";
import { TrendLabel } from "../utils/trend";
import {
  DisplaySignalType,
  displayToLevelType,
  resolveDisplayState,
  resolveTradeReadyStatus,
} from "../utils/signalDisplay";

interface SignalBadgeProps {
  signal: Signal | null;
  /** 4-hour trend label — gates BUY/SELL vs WAIT. */
  trend4h: TrendLabel;
  /** Live BTC price from WebSocket — used for current entry and TP/SL. */
  currentPrice: number | null;
  /** Latest ATR(14) from 1M indicators for TP/SL recalculation. */
  atr14: number | null;
  /** Fear & Greed index value for trade-ready gate. */
  fearGreed: number | null;
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

const DISPLAY_CONFIG: Record<
  DisplaySignalType,
  { label: string; colorClass: string; glowClass: string; emoji: string }
> = {
  BUY: {
    label: "BUY",
    colorClass: "text-green-400 border-green-500",
    glowClass: "shadow-[0_0_20px_rgba(34,197,94,0.3)]",
    emoji: "🟢",
  },
  SELL: {
    label: "SELL",
    colorClass: "text-red-400 border-red-500",
    glowClass: "shadow-[0_0_20px_rgba(239,68,68,0.3)]",
    emoji: "🔴",
  },
  WAIT: {
    label: "WAIT",
    colorClass: "text-yellow-400 border-yellow-500",
    glowClass: "",
    emoji: "🟡",
  },
  HOLD: {
    label: "HOLD",
    colorClass: "text-gray-400 border-gray-500",
    glowClass: "",
    emoji: "⚪",
  },
};

const TRADE_READY_CONFIG = {
  ready: {
    emoji: "✅",
    text: "All conditions met — ready to trade",
    className: "text-emerald-400",
  },
  waiting_4h: {
    emoji: "⏳",
    text: "Waiting for 4H confirmation",
    className: "text-yellow-400",
  },
  not_met: {
    emoji: "❌",
    text: "Conditions not met — hold",
    className: "text-brand-muted",
  },
} as const;

export function SignalBadge({
  signal,
  trend4h,
  currentPrice,
  atr14,
  fearGreed,
}: SignalBadgeProps) {
  const [, setTick] = useState(0);
  const fresh = signal != null && isSignalFresh(signal.generated_at);
  const displayState = resolveDisplayState(signal, trend4h);
  const tradeReady = resolveTradeReadyStatus(signal, trend4h, fearGreed);
  const tradeReadyConfig = TRADE_READY_CONFIG[tradeReady];

  useEffect(() => {
    if (!fresh) return;
    const id = window.setInterval(() => setTick((t) => t + 1), 1000);
    return () => window.clearInterval(id);
  }, [fresh, signal?.generated_at]);

  if (!signal || !fresh) {
    const idleReady = TRADE_READY_CONFIG.not_met;
    return (
      <div className="space-y-2">
        <div className="card flex flex-col items-center justify-center py-8 gap-2">
          <div className="text-4xl">⚪</div>
          <p className="text-brand-muted text-sm">HOLD — no active signal</p>
          <p className="text-brand-muted text-xs">
            {signal && !fresh
              ? "Last signal expired (older than 5 minutes)"
              : "Waiting for fresh entry signal…"}
          </p>
        </div>
        <p className={clsx("text-center text-sm", idleReady.className)}>
          {idleReady.emoji} {idleReady.text}
        </p>
      </div>
    );
  }

  const config = DISPLAY_CONFIG[displayState];
  const isActionable = displayState === "BUY" || displayState === "SELL";
  const levelType = displayToLevelType(displayState, signal.signal_type);
  const showLevels = displayState !== "HOLD";

  const liveEntry = currentPrice ?? signal.entry_price;
  const liveLevels =
    liveEntry != null && showLevels
      ? computeLiveLevels(liveEntry, atr14, levelType)
      : null;
  const displayTp = liveLevels?.tp ?? signal.take_profit;
  const displaySl = liveLevels?.sl ?? signal.stop_loss;
  const displayRr = liveLevels?.rr ?? signal.risk_reward_ratio;
  const usingLivePrice = currentPrice != null && currentPrice !== signal.entry_price;

  return (
    <div className="space-y-2">
      <div
        className={clsx(
          "card flex flex-col items-center gap-3 py-6 border-2 transition-all duration-500 animate-slide-in",
          config.colorClass,
          config.glowClass,
          isActionable && "animate-pulse_slow"
        )}
      >
      <div className="flex items-center gap-3">
        <span className="text-4xl">{config.emoji}</span>
        <div className="text-center">
          <div className={clsx("text-3xl font-bold tracking-widest", config.colorClass)}>
            {config.label}
          </div>
          <div className="text-brand-muted text-sm mt-1">
            {signal.confidence.toFixed(1)}% confidence · {signal.indicators_agreed}{" "}
            indicators agreed
          </div>
          {displayState === "WAIT" && (
            <div className="text-yellow-400/90 text-xs mt-1">
              1M entry ready — 4H trend is {trend4h}
            </div>
          )}
        </div>
      </div>

      {showLevels && (
        <div className="w-full mt-2 space-y-2 text-center">
          <p className="text-brand-muted text-xs">
            Signal generated {timeAgoSeconds(signal.generated_at)}
            {usingLivePrice && (
              <span className="block text-brand-muted/80">
                Original entry {formatPrice(signal.entry_price)}
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

      {displayRr != null && displayRr > 0 && showLevels && (
        <div className="text-brand-muted text-sm">
          R:R = <span className="text-brand-blue">{fmt(displayRr, 2)}:1</span>
        </div>
      )}
      </div>

      <p className={clsx("text-center text-sm", tradeReadyConfig.className)}>
        {tradeReadyConfig.emoji} {tradeReadyConfig.text}
      </p>
    </div>
  );
}
