/**
 * Operational status bar — polls /api/status and shows system health at a glance.
 */

import clsx from "clsx";
import { useApi } from "../hooks/useApi";
import { SystemStatus } from "../utils/types";

function Pill({
  label,
  ok,
  detail,
}: {
  label: string;
  ok: boolean;
  detail: string;
}) {
  return (
    <div
      className={clsx(
        "flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs",
        ok
          ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
          : "border-red-500/30 bg-red-500/10 text-red-300"
      )}
      title={detail}
    >
      <span
        className={clsx(
          "h-2 w-2 rounded-full",
          ok ? "bg-emerald-400" : "bg-red-400"
        )}
      />
      <span className="font-medium">{label}</span>
      <span className="text-brand-muted">{detail}</span>
    </div>
  );
}

function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

export function StatusBar() {
  const { data: status, loading } = useApi<SystemStatus>("/api/status", 30_000);

  if (loading && !status) {
    return (
      <div className="rounded-xl border border-brand-border bg-brand-card px-4 py-2 text-xs text-brand-muted">
        Loading system status…
      </div>
    );
  }

  if (!status) return null;

  const wsOk =
    status.ws_connected ||
    (status.ws_last_message_seconds != null && status.ws_last_message_seconds < 120);

  return (
    <div className="rounded-xl border border-brand-border bg-brand-card px-4 py-3">
      <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-brand-muted">
        System Status
      </div>
      <div className="flex flex-wrap gap-2">
        <Pill
          label="DB"
          ok={status.db_connected}
          detail={status.db_connected ? "connected" : "offline"}
        />
        <Pill
          label="WS"
          ok={wsOk}
          detail={
            status.ws_connected
              ? "live"
              : status.ws_last_message_seconds != null
                ? `${status.ws_last_message_seconds}s ago`
                : "waiting"
          }
        />
        <Pill
          label="1M"
          ok={status.candles_1m >= 3}
          detail={`${status.candles_1m} candles`}
        />
        <Pill
          label="4H"
          ok={status.candles_4h >= 50}
          detail={`${status.candles_4h} candles`}
        />
        <Pill
          label="News"
          ok={status.news_count > 0}
          detail={`${status.news_count} articles`}
        />
        <Pill
          label="F&G"
          ok={status.fear_greed_poll_alive === true}
          detail={
            status.fear_greed != null
              ? `${status.fear_greed}${status.fear_greed_poll_alive ? "" : " (stale)"}`
              : "—"
          }
        />
        <Pill
          label="Uptime"
          ok={status.startup_ready}
          detail={formatUptime(status.uptime_seconds)}
        />
      </div>
    </div>
  );
}
