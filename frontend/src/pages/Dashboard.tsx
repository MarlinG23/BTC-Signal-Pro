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

import { useCallback, useEffect, useRef, useState } from "react";
import { useWebSocket } from "../hooks/useWebSocket";
import { useApi } from "../hooks/useApi";
import {
  AlertItem,
  FearGreedData,
  IndicatorSnapshot,
  NewsItem,
  Signal,
  WaitSignal,
  WsMessage,
} from "../utils/types";

import { PriceHeader } from "../components/PriceHeader";
import { SignalBadge } from "../components/SignalBadge";
import { IndicatorsPanel } from "../components/IndicatorsPanel";
import { TrendPanel } from "../components/TrendPanel";
import { MtfConfluencePanel } from "../components/MtfConfluencePanel";
import { FearGreedGauge } from "../components/FearGreedGauge";
import { NewsFeed } from "../components/NewsFeed";
import { AlertLog } from "../components/AlertLog";
import { SignalHistory } from "../components/SignalHistory";
import { BacktestPanel } from "../components/BacktestPanel";
import { StatusBar } from "../components/StatusBar";
import { isSignalFresh } from "../utils/signalFreshness";
import { deriveTrend } from "../utils/trend";
import { playSignalBeep, unlockAudio } from "../utils/audio";

export function Dashboard() {
  const [livePrice, setLivePrice] = useState<number | null>(null);
  const [candleCount, setCandleCount] = useState(0);
  const [indicators, setIndicators] = useState<IndicatorSnapshot | null>(null);
  const [latestSignal, setLatestSignal] = useState<Signal | null>(null);
  const [latestWait, setLatestWait] = useState<WaitSignal | null>(null);
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
    60_000 // refresh every minute; backend polls hourly
  );
  const { data: snap4h } = useApi<IndicatorSnapshot>(
    "/api/indicators/4h",
    60_000
  );
  const trend4h = deriveTrend(snap4h).label;

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
        setLatestWait(null);
        const bullish =
          sig.signal_type === "BUY" || sig.signal_type === "STRONG_BUY";
        playSignalBeep(bullish);
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

      case "signal_wait": {
        const wait = msg as unknown as WaitSignal & { type: string };
        setLatestWait({
          signal_type: wait.signal_type,
          confidence: wait.confidence,
          entry_price: wait.entry_price,
          take_profit: wait.take_profit,
          stop_loss: wait.stop_loss,
          risk_reward_ratio: wait.risk_reward_ratio,
          indicators_agreed: wait.indicators_agreed,
          generated_at: wait.generated_at,
          display_state: "WAIT",
          block_reason: wait.block_reason as string,
          trend_4h: wait.trend_4h as number | undefined,
          fear_greed: wait.fear_greed as number | null | undefined,
        });
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
          updated_at: msg.updated_at as string | undefined,
        });
        break;
      }
    }
  }, []);

  const { connected } = useWebSocket({ onMessage: handleWsMessage });

  useEffect(() => {
    const unlock = () => {
      void unlockAudio();
    };
    document.addEventListener("click", unlock, { once: true });
    document.addEventListener("touchstart", unlock, { once: true });
    return () => {
      document.removeEventListener("click", unlock);
      document.removeEventListener("touchstart", unlock);
    };
  }, []);

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

  // Use the most recent fresh signal from live WS or historical API (< 5 min)
  const candidateSignal =
    latestSignal ?? (historicalSignals && historicalSignals[0]) ?? null;
  const displaySignal =
    candidateSignal && isSignalFresh(candidateSignal.generated_at)
      ? candidateSignal
      : null;

  const displayWait =
    latestWait && isSignalFresh(latestWait.generated_at) && !displaySignal
      ? latestWait
      : null;

  return (
    <div className="min-h-screen bg-brand-dark">
      <div className="max-w-7xl mx-auto px-4 py-6">
        {/* Header */}
        <PriceHeader
          price={livePrice}
          connected={connected}
          candles={candleCount}
        />

        <StatusBar />

        {/* Main grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Left column */}
          <div className="lg:col-span-2 space-y-4">
            {/* Signal Badge — most prominent element */}
            <SignalBadge
              signal={displaySignal}
              waitSignal={displayWait}
              trend4h={trend4h}
              currentPrice={livePrice}
              atr14={indicators?.atr_14 ?? null}
              fearGreed={
                fearGreed?.value ?? initialFearGreed?.value ?? null
              }
            />

            {/* Multi-timeframe: TREND (4H) vs ENTRY (1M) */}
            <TrendPanel snapshot1m={indicators} />

            {/* Confluence filter: 15m/30m/1h/2h agreement gate */}
            <MtfConfluencePanel />

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
