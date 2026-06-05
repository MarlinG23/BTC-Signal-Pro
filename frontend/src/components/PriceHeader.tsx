/**
 * Live BTC price header with 24h change indicator.
 * Shows the real-time price fed from the WebSocket connection.
 */

import clsx from "clsx";
import { formatPrice } from "../utils/format";
import { Activity, Wifi, WifiOff } from "lucide-react";

interface PriceHeaderProps {
  price: number | null;
  connected: boolean;
  candles: number;
}

export function PriceHeader({ price, connected, candles }: PriceHeaderProps) {
  return (
    <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-6">
      {/* Brand */}
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl bg-brand-green/10 border border-brand-green/30 flex items-center justify-center">
          <span className="text-brand-green text-lg font-bold">₿</span>
        </div>
        <div>
          <h1 className="text-xl font-bold text-white tracking-tight">BTC Signal Pro</h1>
          <p className="text-brand-muted text-xs">Live trading signals</p>
        </div>
      </div>

      {/* Live Price */}
      <div className="flex flex-col items-end">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-brand-green" />
          <span
            className={clsx(
              "text-3xl font-bold font-mono transition-all duration-300",
              price ? "text-white" : "text-brand-muted"
            )}
          >
            {price ? formatPrice(price) : "Loading…"}
          </span>
        </div>
        <div className="flex items-center gap-2 mt-1">
          {connected ? (
            <>
              <Wifi className="w-3 h-3 text-brand-green" />
              <span className="text-brand-green text-xs">Live · {candles} candles</span>
            </>
          ) : (
            <>
              <WifiOff className="w-3 h-3 text-red-400" />
              <span className="text-red-400 text-xs">Reconnecting…</span>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
