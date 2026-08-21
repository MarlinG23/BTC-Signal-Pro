/**
 * Session-scoped live data. Stays mounted across tab routes so the
 * WebSocket, signal beeps, WAIT state, and merged history are not reset
 * when the user switches categories.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useWebSocket } from "../hooks/useWebSocket";
import { useApi } from "../hooks/useApi";
import {
  AlertItem,
  BacktestResult,
  FearGreedData,
  IndicatorSnapshot,
  NewsItem,
  Signal,
  Snapshot4H,
  WaitSignal,
  WsMessage,
} from "../utils/types";
import { isSignalFresh } from "../utils/signalFreshness";
import { deriveTrend, type TrendLabel } from "../utils/trend";
import { playSignalBeep, unlockAudio } from "../utils/audio";

const API_BASE = import.meta.env.VITE_API_URL || "";

export interface LiveDataValue {
  livePrice: number | null;
  candleCount: number;
  indicators: IndicatorSnapshot | null;
  snap4h: Snapshot4H | null;
  snap4hLoading: boolean;
  trend4h: TrendLabel;
  connected: boolean;
  displaySignal: Signal | null;
  displayWait: WaitSignal | null;
  fearGreed: FearGreedData | null;
  allAlerts: AlertItem[];
  allNews: NewsItem[];
  historicalSignals: Signal[] | null;
  signalsLoading: boolean;
  newsLoading: boolean;
  backtestDays: number;
  setBacktestDays: (days: number) => void;
  backtestResult: BacktestResult | null;
  backtestError: string | null;
  backtestLoading: boolean;
  runBacktest: () => Promise<void>;
}

const LiveDataContext = createContext<LiveDataValue | null>(null);

export function useLiveData(): LiveDataValue {
  const ctx = useContext(LiveDataContext);
  if (!ctx) {
    throw new Error("useLiveData must be used within LiveDataProvider");
  }
  return ctx;
}

export function LiveDataProvider({ children }: { children: ReactNode }) {
  const [livePrice, setLivePrice] = useState<number | null>(null);
  const [candleCount, setCandleCount] = useState(0);
  const [indicators, setIndicators] = useState<IndicatorSnapshot | null>(null);
  const [latestSignal, setLatestSignal] = useState<Signal | null>(null);
  const [latestWait, setLatestWait] = useState<WaitSignal | null>(null);
  const [fearGreedWs, setFearGreedWs] = useState<FearGreedData | null>(null);
  const [liveAlerts, setLiveAlerts] = useState<AlertItem[]>([]);
  const [liveNews, setLiveNews] = useState<NewsItem[]>([]);

  const { data: historicalSignals, loading: signalsLoading } = useApi<Signal[]>(
    "/api/signals/latest?limit=50",
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
  const { data: initialFearGreed } = useApi<FearGreedData>(
    "/api/fear-greed",
    60_000
  );
  const { data: snap4h, loading: snap4hLoading } = useApi<Snapshot4H>(
    "/api/indicators/4h",
    60_000
  );
  const trend4h = deriveTrend(snap4h).label;

  const [backtestDays, setBacktestDays] = useState(30);
  const [backtestResult, setBacktestResult] = useState<BacktestResult | null>(
    null
  );
  const [backtestError, setBacktestError] = useState<string | null>(null);
  const [backtestLoading, setBacktestLoading] = useState(false);

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
        setFearGreedWs({
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

  const runBacktest = useCallback(async () => {
    setBacktestLoading(true);
    setBacktestError(null);
    setBacktestResult(null);

    for (let attempt = 1; attempt <= 3; attempt++) {
      try {
        const res = await fetch(`${API_BASE}/api/backtest?days=${backtestDays}`);
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(
            (body as { detail?: string }).detail || `HTTP ${res.status}`
          );
        }
        const data = (await res.json()) as BacktestResult;
        setBacktestResult(data);
        break;
      } catch (err) {
        if (attempt === 3) {
          setBacktestError(
            err instanceof Error ? err.message : "Backtest failed"
          );
        } else {
          await new Promise((r) => setTimeout(r, 1000 * attempt));
        }
      }
    }

    setBacktestLoading(false);
  }, [backtestDays]);

  const allAlerts: AlertItem[] = useMemo(
    () => [...liveAlerts, ...(historicalAlerts ?? [])].slice(0, 50),
    [liveAlerts, historicalAlerts]
  );

  const allNews: NewsItem[] = useMemo(() => {
    const seenTitles = new Set<string>();
    const merged: NewsItem[] = [];
    for (const item of [...liveNews, ...(historicalNews ?? [])]) {
      if (!seenTitles.has(item.title)) {
        seenTitles.add(item.title);
        merged.push(item);
      }
    }
    return merged;
  }, [liveNews, historicalNews]);

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

  const value = useMemo<LiveDataValue>(
    () => ({
      livePrice,
      candleCount,
      indicators,
      snap4h: snap4h ?? null,
      snap4hLoading: snap4hLoading && !snap4h,
      trend4h,
      connected,
      displaySignal,
      displayWait,
      fearGreed: fearGreedWs ?? initialFearGreed ?? null,
      allAlerts,
      allNews,
      historicalSignals,
      signalsLoading,
      newsLoading,
      backtestDays,
      setBacktestDays,
      backtestResult,
      backtestError,
      backtestLoading,
      runBacktest,
    }),
    [
      livePrice,
      candleCount,
      indicators,
      snap4h,
      snap4hLoading,
      trend4h,
      connected,
      displaySignal,
      displayWait,
      fearGreedWs,
      initialFearGreed,
      allAlerts,
      allNews,
      historicalSignals,
      signalsLoading,
      newsLoading,
      backtestDays,
      backtestResult,
      backtestError,
      backtestLoading,
      runBacktest,
    ]
  );

  return (
    <LiveDataContext.Provider value={value}>{children}</LiveDataContext.Provider>
  );
}
