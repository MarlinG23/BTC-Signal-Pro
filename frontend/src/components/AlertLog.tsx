/**
 * Alert history log showing recent alerts with type and timestamp.
 * New alerts animate in when they arrive via WebSocket.
 */

import clsx from "clsx";
import { Bell, Zap, Newspaper, TrendingDown, AlertCircle } from "lucide-react";
import { AlertItem, AlertType } from "../utils/types";
import { timeAgo, truncate } from "../utils/format";

interface AlertLogProps {
  alerts: AlertItem[];
}

const ALERT_CONFIG: Record<
  AlertType,
  { icon: React.ReactNode; className: string; label: string }
> = {
  PRICE_LEVEL: {
    icon: <AlertCircle className="w-4 h-4" />,
    className: "text-yellow-400 bg-yellow-400/10 border-yellow-400/20",
    label: "Price Level",
  },
  NEW_SIGNAL: {
    icon: <Zap className="w-4 h-4" />,
    className: "text-brand-blue bg-brand-blue/10 border-brand-blue/20",
    label: "Signal",
  },
  BREAKING_NEWS: {
    icon: <Newspaper className="w-4 h-4" />,
    className: "text-purple-400 bg-purple-400/10 border-purple-400/20",
    label: "News",
  },
  LIQUIDATION: {
    icon: <TrendingDown className="w-4 h-4" />,
    className: "text-red-400 bg-red-400/10 border-red-400/20",
    label: "Liquidation",
  },
};

function AlertRow({ alert }: { alert: AlertItem }) {
  const config = ALERT_CONFIG[alert.alert_type] ?? ALERT_CONFIG.PRICE_LEVEL;

  return (
    <div className="flex items-start gap-3 py-2 border-b border-brand-border last:border-0 animate-slide-in">
      <div className={clsx("flex items-center justify-center w-7 h-7 rounded-lg border shrink-0 mt-0.5", config.className)}>
        {config.icon}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <span className={clsx("text-xs font-medium border rounded px-2 py-0.5", config.className)}>
            {config.label}
          </span>
          <span className="text-xs text-brand-muted whitespace-nowrap">
            {timeAgo(alert.triggered_at)}
          </span>
        </div>
        <p className="text-sm text-white mt-1 leading-snug">
          {truncate(alert.message, 120)}
        </p>
      </div>
    </div>
  );
}

export function AlertLog({ alerts }: AlertLogProps) {
  return (
    <div className="card">
      <div className="flex items-center gap-2 mb-4">
        <Bell className="w-4 h-4 text-brand-muted" />
        <h2 className="text-sm font-semibold text-brand-muted uppercase tracking-wider">
          Alert History
        </h2>
        {alerts.length > 0 && (
          <span className="ml-auto bg-brand-blue/20 text-brand-blue text-xs rounded-full px-2 py-0.5 border border-brand-blue/30">
            {alerts.length}
          </span>
        )}
      </div>

      {alerts.length === 0 ? (
        <div className="flex items-center justify-center py-6 text-brand-muted text-sm">
          No alerts yet
        </div>
      ) : (
        <div className="space-y-0 max-h-80 overflow-y-auto">
          {alerts.slice(0, 50).map((alert) => (
            <AlertRow key={alert.id} alert={alert} />
          ))}
        </div>
      )}
    </div>
  );
}
