/**
 * Live 1-minute BTC candlestick chart with Entry / TP / SL needles.
 * History comes from GET /api/candles; new bars append from the closed-candle
 * WebSocket payload; last price follows price_tick.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import {
  ColorType,
  LineStyle,
  createChart,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { useApi } from "../hooks/useApi";
import { useLiveData } from "../context/LiveDataContext";
import { CandleBar, Signal, SignalType, WaitSignal } from "../utils/types";
import { computeLiveLevels } from "../utils/liveLevels";
import { isSignalFresh } from "../utils/signalFreshness";
import {
  DisplaySignalType,
  displayToLevelType,
  resolveDisplayState,
} from "../utils/signalDisplay";
import { TrendLabel } from "../utils/trend";

const CHART_HEIGHT = 340;
const MAX_BARS = 500;

type LineKey = "last" | "entry" | "tp" | "sl";

interface NeedleLevels {
  entry: number;
  tp: number | null;
  sl: number | null;
}

function upsertBar(bars: CandleBar[], bar: CandleBar): CandleBar[] {
  if (bars.length === 0) return [bar];
  const last = bars[bars.length - 1];
  if (bar.time === last.time) {
    return [...bars.slice(0, -1), bar];
  }
  if (bar.time > last.time) {
    const next = [...bars, bar];
    return next.length > MAX_BARS ? next.slice(-MAX_BARS) : next;
  }
  return bars;
}

function waitAsSignal(wait: WaitSignal): Signal {
  return {
    signal_type: wait.signal_type,
    confidence: wait.confidence,
    entry_price: wait.entry_price,
    take_profit: wait.take_profit,
    stop_loss: wait.stop_loss,
    risk_reward_ratio: wait.risk_reward_ratio,
    indicators_agreed: wait.indicators_agreed,
    generated_at: wait.generated_at,
    risk_tier: wait.risk_tier,
    rsi_4h: wait.rsi_4h,
    size_multiplier: wait.size_multiplier,
    tp_multiplier: wait.tp_multiplier,
    sl_multiplier: wait.sl_multiplier,
  };
}

function resolveNeedles(
  signal: Signal | null,
  waitSignal: WaitSignal | null,
  trend4h: TrendLabel,
  currentPrice: number | null,
  atr14: number | null
): NeedleLevels | null {
  const freshFired = signal != null && isSignalFresh(signal.generated_at);
  const freshWait = waitSignal != null && isSignalFresh(waitSignal.generated_at);
  if (!freshFired && !freshWait) return null;

  const entrySignal: Signal = freshFired ? signal! : waitAsSignal(waitSignal!);
  const displayState: DisplaySignalType = freshFired
    ? resolveDisplayState(signal, trend4h)
    : "WAIT";
  if (displayState === "HOLD") return null;

  const levelType: SignalType = displayToLevelType(
    displayState,
    entrySignal.signal_type
  );
  const liveEntry = currentPrice ?? entrySignal.entry_price;
  const liveLevels = computeLiveLevels(
    liveEntry,
    atr14,
    levelType,
    entrySignal.tp_multiplier ?? 1,
    entrySignal.sl_multiplier ?? 1
  );

  return {
    entry: liveEntry,
    tp: liveLevels?.tp ?? entrySignal.take_profit,
    sl: liveLevels?.sl ?? entrySignal.stop_loss,
  };
}

export function LiveChart() {
  const {
    livePrice,
    latestClosedCandle,
    displaySignal,
    displayWait,
    trend4h,
    indicators,
  } = useLiveData();
  const { data: history, loading, error } = useApi<CandleBar[]>(
    "/api/candles?interval=1m&limit=200"
  );

  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const linesRef = useRef<Partial<Record<LineKey, IPriceLine>>>({});
  const [chartReady, setChartReady] = useState(0);
  const latestClosedRef = useRef<CandleBar | null>(null);

  const [bars, setBars] = useState<CandleBar[]>([]);

  latestClosedRef.current = latestClosedCandle;

  useEffect(() => {
    if (!history || history.length === 0) return;
    const extra = latestClosedRef.current;
    setBars(extra ? upsertBar(history, extra) : history);
  }, [history]);

  useEffect(() => {
    if (!latestClosedCandle) return;
    setBars((prev) => upsertBar(prev, latestClosedCandle));
  }, [latestClosedCandle]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const chart = createChart(el, {
      width: el.clientWidth,
      height: CHART_HEIGHT,
      layout: {
        background: { type: ColorType.Solid, color: "#12121a" },
        textColor: "#888899",
        fontFamily: "'JetBrains Mono', monospace",
      },
      grid: {
        vertLines: { color: "#1e1e2e" },
        horzLines: { color: "#1e1e2e" },
      },
      rightPriceScale: {
        borderColor: "#1e1e2e",
      },
      timeScale: {
        borderColor: "#1e1e2e",
        timeVisible: true,
        secondsVisible: false,
      },
      crosshair: {
        vertLine: { color: "#888899", width: 1, style: LineStyle.Dotted },
        horzLine: { color: "#888899", width: 1, style: LineStyle.Dotted },
      },
    });

    const series = chart.addCandlestickSeries({
      upColor: "#00ff88",
      downColor: "#ff3b5c",
      borderVisible: false,
      wickUpColor: "#00ff88",
      wickDownColor: "#ff3b5c",
    });

    chartRef.current = chart;
    seriesRef.current = series;
    setChartReady((n) => n + 1);

    const ro = new ResizeObserver((entries) => {
      const width = Math.floor(entries[0]?.contentRect.width ?? 0);
      if (width > 0) {
        chart.applyOptions({ width });
      }
    });
    ro.observe(el);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      linesRef.current = {};
    };
  }, []);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series || bars.length === 0) return;
    series.setData(
      bars.map((b) => ({
        time: b.time as UTCTimestamp,
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
      }))
    );
    chartRef.current?.timeScale().scrollToRealTime();
  }, [bars, chartReady]);

  const needles = useMemo(
    () =>
      resolveNeedles(
        displaySignal,
        displayWait,
        trend4h,
        livePrice,
        indicators?.atr_14 ?? null
      ),
    [displaySignal, displayWait, trend4h, livePrice, indicators?.atr_14]
  );

  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;

    const upsert = (
      key: LineKey,
      price: number | null | undefined,
      color: string,
      title: string,
      lineStyle: LineStyle
    ) => {
      const existing = linesRef.current[key];
      if (price == null || !Number.isFinite(price)) {
        if (existing) {
          series.removePriceLine(existing);
          delete linesRef.current[key];
        }
        return;
      }
      if (existing) {
        existing.applyOptions({ price, color, title, lineStyle });
        return;
      }
      linesRef.current[key] = series.createPriceLine({
        price,
        color,
        title,
        lineStyle,
        lineWidth: 1,
        axisLabelVisible: true,
      });
    };

    upsert("last", livePrice, "#00bfff", "Last", LineStyle.Solid);
    upsert("entry", needles?.entry, "#ffffff", "Entry", LineStyle.Solid);
    upsert("tp", needles?.tp, "#00ff88", "TP", LineStyle.Dashed);
    upsert("sl", needles?.sl, "#ff3b5c", "SL", LineStyle.Dashed);
  }, [livePrice, needles, bars.length, chartReady]);

  const empty = bars.length === 0;

  return (
    <div className="card p-3">
      <div className="flex items-baseline justify-between mb-2 px-1">
        <h2 className="text-sm font-semibold text-brand-muted uppercase tracking-wider">
          BTC 1M
        </h2>
        <span className="text-brand-muted text-xs">
          {needles ? "Entry / TP / SL" : "Last price"}
        </span>
      </div>
      <div className="relative" style={{ height: CHART_HEIGHT }}>
        <div ref={containerRef} className="absolute inset-0" />
        {empty && (
          <div className="absolute inset-0 flex items-center justify-center text-brand-muted text-xs pointer-events-none">
            {loading
              ? "Loading candles…"
              : error
                ? "Waiting for candles…"
                : "Waiting for candles…"}
          </div>
        )}
      </div>
    </div>
  );
}
