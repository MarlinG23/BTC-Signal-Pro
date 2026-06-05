/**
 * Backtesting results panel. Fetches stats from the /api/backtest endpoint
 * and displays key metrics in a card grid.
 */

import { useState } from "react";
import clsx from "clsx";
import { PlayCircle, TrendingUp, TrendingDown } from "lucide-react";
import { BacktestResult } from "../utils/types";
import { fmt, formatPct } from "../utils/format";

interface BacktestPanelProps {
  apiBase?: string;
}

interface MetricCardProps {
  label: string;
  value: string;
  positive?: boolean;
  negative?: boolean;
  neutral?: boolean;
}

function MetricCard({ label, value, positive, negative }: MetricCardProps) {
  return (
    <div className="bg-brand-dark border border-brand-border rounded-lg p-3 text-center">
      <p className="text-brand-muted text-xs uppercase tracking-wider mb-1">{label}</p>
      <p
        className={clsx("text-lg font-bold font-mono", {
          "text-emerald-400": positive,
          "text-red-400": negative,
          "text-white": !positive && !negative,
        })}
      >
        {value}
      </p>
    </div>
  );
}

export function BacktestPanel({ apiBase = "" }: BacktestPanelProps) {
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runBacktest = async () => {
    setLoading(true);
    setError(null);
    setResult(null);

    for (let attempt = 1; attempt <= 3; attempt++) {
      try {
        const res = await fetch(`${apiBase}/api/backtest?days=${days}`);
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error((body as { detail?: string }).detail || `HTTP ${res.status}`);
        }
        const data = (await res.json()) as BacktestResult;
        setResult(data);
        break;
      } catch (err) {
        if (attempt === 3) {
          setError(err instanceof Error ? err.message : "Backtest failed");
        } else {
          await new Promise((r) => setTimeout(r, 1000 * attempt));
        }
      }
    }

    setLoading(false);
  };

  return (
    <div className="card">
      <div className="flex items-center gap-2 mb-4">
        <TrendingUp className="w-4 h-4 text-brand-muted" />
        <h2 className="text-sm font-semibold text-brand-muted uppercase tracking-wider">
          Backtester
        </h2>
      </div>

      {/* Controls */}
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <div className="flex items-center gap-2">
          <label className="text-brand-muted text-sm">Days:</label>
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="bg-brand-dark border border-brand-border rounded-lg px-3 py-1.5 text-sm text-white"
          >
            {[7, 14, 30, 60, 90, 180].map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </div>
        <button
          onClick={runBacktest}
          disabled={loading}
          className={clsx(
            "flex items-center gap-2 px-4 py-1.5 rounded-lg text-sm font-medium transition-all",
            loading
              ? "bg-brand-border text-brand-muted cursor-not-allowed"
              : "bg-brand-green/20 text-brand-green border border-brand-green/30 hover:bg-brand-green/30"
          )}
        >
          <PlayCircle className="w-4 h-4" />
          {loading ? "Running…" : "Run Backtest"}
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-400/10 border border-red-400/30 rounded-lg p-3 text-red-400 text-sm mb-4">
          {error}
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="space-y-4 animate-slide-in">
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            <MetricCard
              label="Total Signals"
              value={String(result.total_signals)}
            />
            <MetricCard
              label="Total Trades"
              value={String(result.total_trades)}
            />
            <MetricCard
              label="Win Rate"
              value={formatPct(result.win_rate_pct, 1)}
              positive={result.win_rate_pct >= 55}
              negative={result.win_rate_pct < 45}
            />
            <MetricCard
              label="Avg Profit"
              value={formatPct(result.avg_profit_pct, 2)}
              positive={result.avg_profit_pct > 0}
            />
            <MetricCard
              label="Avg Loss"
              value={formatPct(result.avg_loss_pct, 2)}
              negative={result.avg_loss_pct < 0}
            />
            <MetricCard
              label="Profit Factor"
              value={
                result.profit_factor === Infinity
                  ? "∞"
                  : fmt(result.profit_factor, 2)
              }
              positive={result.profit_factor > 1.5}
              negative={result.profit_factor < 1}
            />
            <MetricCard
              label="Max Drawdown"
              value={formatPct(-result.max_drawdown_pct, 2)}
              negative={result.max_drawdown_pct > 10}
            />
            <MetricCard
              label="Sharpe Proxy"
              value={fmt(result.sharpe_proxy, 3)}
              positive={result.sharpe_proxy > 0.5}
            />
            <MetricCard
              label="Total Return"
              value={formatPct(result.total_return_pct, 2)}
              positive={result.total_return_pct > 0}
              negative={result.total_return_pct < 0}
            />
          </div>
          <p className="text-brand-muted text-xs text-right">
            Tested on {result.candles_used.toLocaleString()} candles over {days} days
          </p>
        </div>
      )}

      {!result && !loading && !error && (
        <p className="text-brand-muted text-sm text-center py-4">
          Click "Run Backtest" to test signal performance on historical data.
        </p>
      )}
    </div>
  );
}
