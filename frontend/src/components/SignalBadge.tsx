/**
 * Prominent animated signal badge displayed at the top of the dashboard.
 * Shows BUY/SELL when gates pass; WAIT when 1M entry blocked; HOLD when idle.
 */

import { useEffect, useState } from "react";
import clsx from "clsx";
import { Signal, SignalType, WaitSignal } from "../utils/types";
import { formatPrice, fmt, timeAgoSeconds } from "../utils/format";
import { isSignalFresh } from "../utils/signalFreshness";
import { TrendLabel } from "../utils/trend";
import { resolveIdleReason } from "../utils/idleReason";
import {
  DisplaySignalType,
  displayToLevelType,
  resolveDisplayState,
  resolveTradeReadyStatus,
} from "../utils/signalDisplay";

interface SignalBadgeProps {
  signal: Signal | null;
  waitSignal: WaitSignal | null;
  trend4h: TrendLabel;
  currentPrice: number | null;
  atr14: number | null;
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

export function SignalBadge({
  signal,
  waitSignal,
  trend4h,
  currentPrice,
  atr14,
  fearGreed,
}: SignalBadgeProps) {
  const [, setTick] = useState(0);
  const freshFired = signal != null && isSignalFresh(signal.generated_at);
  const freshWait = waitSignal != null && isSignalFresh(waitSignal.generated_at);

  useEffect(() => {
    if (!freshFired && !freshWait) return;
    const id = window.setInterval(() => setTick((t) => t + 1), 1000);
    return () => window.clearInterval(id);
  }, [freshFired, freshWait, signal?.generated_at, waitSignal?.generated_at]);

  const idleReason = resolveIdleReason(trend4h, fearGreed, freshWait ? waitSignal : null);

  if (!freshFired && !freshWait) {
    return (
      <div className="space-y-2">
        <div className="card flex flex-col items-center justify-center py-8 gap-2">
          <div className="text-4xl">⚪</div>
          <p className="text-brand-muted text-sm">HOLD — no active signal</p>
          <p className="text-brand-muted text-xs">
            {signal && !freshFired
              ? "Last signal expired (older than 5 minutes)"
              : waitSignal && !freshWait
                ? "Last blocked entry expired (older than 5 minutes)"
                : "Waiting for fresh entry signal…"}
          </p>
        </div>
        <p className={clsx("text-center text-sm", idleReason.className)}>
          {idleReason.emoji} {idleReason.text}
        </p>
      </div>
    );
  }

  const entrySignal: Signal = freshFired
    ? signal!
    : {
        signal_type: waitSignal!.signal_type,
        confidence: waitSignal!.confidence,
        entry_price: waitSignal!.entry_price,
        take_profit: waitSignal!.take_profit,
        stop_loss: waitSignal!.stop_loss,
        risk_reward_ratio: waitSignal!.risk_reward_ratio,
        indicators_agreed: waitSignal!.indicators_agreed,
        generated_at: waitSignal!.generated_at,
      };

  const displayState: DisplaySignalType = freshFired
    ? resolveDisplayState(signal, trend4h)
    : "WAIT";

  const tradeReady = freshFired
    ? resolveTradeReadyStatus(signal, trend4h, fearGreed)
    : null;

  const tradeReadyText = freshFired
    ? tradeReady === "ready"
      ? { emoji: "✅", text: "All conditions met — ready to trade", className: "text-emerald-400" }
      : tradeReady === "waiting_4h"
        ? { emoji: "⏳", text: "Waiting for 4H confirmation", className: "text-yellow-400" }
        : { emoji: "❌", text: idleReason.text, className: idleReason.className }
    : idleReason;

  const config = DISPLAY_CONFIG[displayState];
  const isActionable = displayState === "BUY" || displayState === "SELL";
  const levelType = displayToLevelType(displayState, entrySignal.signal_type);
  const showLevels = displayState !== "HOLD";

  const liveEntry = currentPrice ?? entrySignal.entry_price;
  const liveLevels =
    liveEntry != null && showLevels
      ? computeLiveLevels(liveEntry, atr14, levelType)
      : null;
  const displayTp = liveLevels?.tp ?? entrySignal.take_profit;
  const displaySl = liveLevels?.sl ?? entrySignal.stop_loss;
  const displayRr = liveLevels?.rr ?? entrySignal.risk_reward_ratio;
  const usingLivePrice =
    currentPrice != null && currentPrice !== entrySignal.entry_price;

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
              {entrySignal.confidence.toFixed(1)}% confidence ·{" "}
              {entrySignal.indicators_agreed} indicators agreed
            </div>
            {displayState === "WAIT" && waitSignal?.block_reason && (
              <div className="text-yellow-400/90 text-xs mt-2 max-w-md">
                {waitSignal.block_reason}
              </div>
            )}
            {displayState === "WAIT" && freshFired && (
              <div className="text-yellow-400/90 text-xs mt-1">
                1M entry ready — 4H trend is {trend4h}
              </div>
            )}
          </div>
        </div>

        {showLevels && (
          <div className="w-full mt-2 space-y-2 text-center">
            <p className="text-brand-muted text-xs">
              {freshWait ? "Blocked entry" : "Signal"} generated{" "}
              {timeAgoSeconds(entrySignal.generated_at)}
              {usingLivePrice && (
                <span className="block text-brand-muted/80">
                  Original entry {formatPrice(entrySignal.entry_price)}
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
          </div>
        )}

        {displayRr != null && displayRr > 0 && showLevels && (
          <div className="text-brand-muted text-sm">
            R:R = <span className="text-brand-blue">{fmt(displayRr, 2)}:1</span>
          </div>
        )}
      </div>

      <p className={clsx("text-center text-sm", tradeReadyText.className)}>
        {tradeReadyText.emoji} {tradeReadyText.text}
      </p>
    </div>
  );
}
