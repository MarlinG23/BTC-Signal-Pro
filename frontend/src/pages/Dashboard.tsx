/**
 * Main dashboard page — assembles all components into a responsive layout.
 *
 * Layout:
 *   Mobile (< md):  Single column stack
 *   Desktop (≥ md): 2-column layout
 *
 * Live data flow:
 *   WebSocket → price ticks, indicator updates, signals, alerts, news, fear/greed
 *   REST API  → initial signal history, news history, alert history (polled every 30s)
 */

import { useCallback, useRef, useState } from "react";
import { useWebSocket } from "../hooks/useWebSocket";
import { useApi } from "../hooks/useApi";
import {
  AlertItem,
  FearGreedData,
  IndicatorSnapshot,
  NewsItem,
  Signal,
  WsMessage,
} from "../utils/types";

import { PriceHeader } from "../components/PriceHeader";
import { SignalBadge } from "../components/SignalBadge";
import { IndicatorsPanel } from "../components/IndicatorsPanel";
import { TrendPanel } from "../components/TrendPanel";
import { FearGreedGauge } from "../components/FearGreedGauge";
import { NewsFeed } from "../components/NewsFeed";
import { AlertLog } from "../components/AlertLog";
import { SignalHistory } from "../components/SignalHistory";
import { BacktestPanel } from "../components/BacktestPanel";

// Sound alert using Web Audio API — plays a short beep on new signal
function playSignalSound(type: string) {
  try {
    const ctx = new AudioContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.frequency.value =
      type === "STRONG_BUY" || type === "BUY" ? 880 : 440;
    gain.gain.setValueAtTime(0.3, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.5);
    osc.start(ctx.currentTime);
    osc.stop(ctx.currentTime + 0.5);
  } catch {
    // AudioContext may be blocked by browser policy — silently ignore
  }
}

export function Dashboard() {
  const [livePrice, setLivePrice] = useState<number | null>(null);
  const [candleCount, setCandleCount] = useState(0);
  const [indicators, setIndicators] = useState<IndicatorSnapshot | null>(null);
  const [latestSignal, setLatestSignal] = useState<Signal | null>(null);
  const [fearGreed, setFearGreed] = useState<FearGreedData | null>(null);
  const [liveAlerts, setLiveAlerts] = useState<AlertItem[]>([]);
  const [liveNews, setLiveNews] = useState<NewsItem[]>([]);

  // REST data — polled periodically
  const { data: historicalSignals, loading: signalsLoading } = useApi<Signal[]>(
    "/api/signals/latest?limit=20",
    30_000
  );
  const { data: historicalNews, loading: newsLoading } = useApi<NewsItem[]>(
    "/api/news?limit=30",
    60_000
  );
  const { data: historicalAlerts } = useApi<AlertItem[]>(
    "/api/alerts/history?limit=50",
    30_000
  );
  // Fetch Fear & Greed immediately on page load; WS updates will override
  const { data: initialFearGreed } = useApi<FearGreedData>(
    "/api/fear-greed",
    300_000 // refresh every 5 minutes to stay in sync with backend poll
  );

  const nextAlertId = useRef(0);
  const nextNewsId = useRef(-1);

  const handleWsMessage = useCallback((msg: WsMessage) => {
    switch (msg.type) {
      case "price_tick":
        if (typeof msg.price === "number") {
          setLivePrice(msg.price);
        }
        break;

      case "indicators": {
        const snap = msg as unknown as IndicatorSnapshot & { type: string };
        setIndicators(snap);
        if (snap.close_price) {
          setLivePrice(snap.close_price);
          setCandleCount((c) => c + 1);
        }
        break;
      }

      case "signal": {
        const sig = msg as unknown as Signal & { type: string };
        setLatestSignal(sig);
        playSignalSound(sig.signal_type as string);
        // Add to live alerts list
        setLiveAlerts((prev) => [
          {
            id: nextAlertId.current--,
            alert_type: "NEW_SIGNAL",
            message: `${sig.signal_type} — confidence ${(sig.confidence as number).toFixed(1)}%`,
            triggered_at: new Date().toISOString(),
            is_sent: false,
          },
          ...prev.slice(0, 49),
        ]);
        break;
      }

      case "alert": {
        setLiveAlerts((prev) => [
          {
            id: nextAlertId.current--,
            alert_type: msg.alert_type as AlertItem["alert_type"],
            message: (msg.message as string) || "",
            triggered_at: (msg.timestamp as string) || new Date().toISOString(),
            is_sent: false,
          },
          ...prev.slice(0, 49),
        ]);
        break;
      }

      case "news": {
        setLiveNews((prev) => [
          {
            id: nextNewsId.current--,
            source: msg.source as string,
            title: msg.title as string,
            url: "",
            published_at: new Date().toISOString(),
            sentiment: msg.sentiment as NewsItem["sentiment"],
            sentiment_score: msg.score as number | null,
            is_geopolitical: msg.is_geopolitical as boolean,
            geo_keywords: null,
          },
          ...prev.slice(0, 29),
        ]);
        break;
      }

      case "fear_greed": {
        setFearGreed({
          value: msg.value as number,
          classification: msg.classification as string,
          timestamp: msg.timestamp as string,
        });
        break;
      }
    }
  }, []);

  const { connected } = useWebSocket({ onMessage: handleWsMessage });

  // Merge live alerts with historical
  const allAlerts: AlertItem[] = [
    ...liveAlerts,
    ...(historicalAlerts ?? []),
  ].slice(0, 50);

  // Merge live news with historical, deduplicate by title
  const seenTitles = new Set<string>();
  const allNews: NewsItem[] = [];
  for (const item of [...liveNews, ...(historicalNews ?? [])]) {
    if (!seenTitles.has(item.title)) {
      seenTitles.add(item.title);
      allNews.push(item);
    }
  }

  // Use the most recent signal from live WS or historical API
  const displaySignal =
    latestSignal ?? (historicalSignals && historicalSignals[0]) ?? null;

  return (
    <div className="min-h-screen bg-brand-dark">
      <div className="max-w-7xl mx-auto px-4 py-6">
        {/* Header */}
        <PriceHeader
          price={livePrice}
          connected={connected}
          candles={candleCount}
        />

        {/* Main grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Left column */}
          <div className="lg:col-span-2 space-y-4">
            {/* Signal Badge — most prominent element */}
            <SignalBadge signal={displaySignal} />

            {/* Multi-timeframe: TREND (4H) vs ENTRY (1M) */}
            <TrendPanel snapshot1m={indicators} />

            {/* 1M Indicators detail */}
            <IndicatorsPanel snapshot={indicators} />

            {/* Signal History */}
            <SignalHistory
              signals={historicalSignals ?? []}
              loading={signalsLoading}
            />

            {/* Backtester */}
            <BacktestPanel />
          </div>

          {/* Right column */}
          <div className="space-y-4">
            {/* Fear & Greed — live WS takes priority; REST fills in on load */}
            <FearGreedGauge data={fearGreed ?? initialFearGreed ?? null} />

            {/* Alert Log */}
            <AlertLog alerts={allAlerts} />

            {/* News Feed */}
            <NewsFeed
              items={allNews}
              loading={newsLoading && allNews.length === 0}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
