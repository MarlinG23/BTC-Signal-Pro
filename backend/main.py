"""
BTC Signal Pro — FastAPI application entry point.

Startup sequence:
  1. Load config from .env
  2. Initialise PostgreSQL tables
  3. Start Binance WebSocket in background task
  4. Start news polling scheduler
  5. Mount REST + WebSocket routes

All WebSocket connections receive live price ticks, indicator snapshots,
signals, and alerts in real time via a shared broadcaster.
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from alerts.manager import AlertManager, AlertType
from config import settings
from database.connection import AsyncSessionLocal, get_db, init_db
from database.models import Alert, NewsItem, PriceCandle, Signal, TechnicalIndicator
from indicators.binance_ws import BinanceWebSocketClient
from indicators.calculator import Candle, IndicatorCalculator, IndicatorSnapshot
from news.fetcher import NEWS_POLL_INTERVAL_S, NewsFetcher
from news.filter import FakeNewsFilter
from news.sentiment import SentimentAnalyzer
from signals.backtester import BacktestEngine
from signals.engine import SignalEngine, SignalResult

logging.basicConfig(
    level=logging.DEBUG if not settings.is_production else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Shared singletons ─────────────────────────────────────────────────────────
calculator = IndicatorCalculator()        # 1-minute candles (entry timing)
calculator_4h = IndicatorCalculator()     # 4-hour candles  (trend direction)
signal_engine = SignalEngine()
alert_manager = AlertManager(db_session_factory=AsyncSessionLocal)
binance_ws = BinanceWebSocketClient(calculator, calculator_4h=calculator_4h)
sentiment_analyzer = SentimentAnalyzer()
fake_news_filter = FakeNewsFilter()

# Key support/resistance levels (updated periodically via REST endpoint)
_key_levels: list[float] = []

# Latest Fear & Greed snapshot — updated by the news poll loop so the REST
# endpoint can serve it immediately without making an outbound request.
_latest_fear_greed: Optional[dict] = None


# ── Application lifespan ──────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events."""
    logger.info("BTC Signal Pro starting up...")

    # 1. Init DB tables
    try:
        await init_db()
    except Exception as exc:
        logger.error("DB init failed — running without persistence: %s", exc)

    # 2. Register WebSocket callbacks
    binance_ws.on_candle_closed(_on_candle_closed)
    binance_ws.on_price_tick(_on_price_tick)

    # 3. Start Binance WebSocket
    ws_task = asyncio.create_task(binance_ws.run(), name="binance-ws")

    # 4. Start news polling (every 5 minutes)
    news_task = asyncio.create_task(_news_poll_loop(), name="news-poll")

    # 5. Start REST price fallback when Binance WebSocket is geo-blocked/unavailable
    fallback_task = asyncio.create_task(_price_fallback_loop(), name="price-fallback")

    # 6. Start signal outcome checker (runs every 5 minutes)
    outcome_task = asyncio.create_task(_outcome_check_loop(), name="outcome-check")

    logger.info("BTC Signal Pro ready. Listening on %s:%d", settings.APP_HOST, settings.APP_PORT)

    yield  # application runs here

    # Graceful shutdown
    logger.info("Shutting down...")
    await binance_ws.stop()
    ws_task.cancel()
    news_task.cancel()
    fallback_task.cancel()
    outcome_task.cancel()
    try:
        await asyncio.gather(ws_task, news_task, fallback_task, outcome_task, return_exceptions=True)
    except Exception:
        pass
    logger.info("Shutdown complete.")


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="BTC Signal Pro",
    description="Production-grade Bitcoin trading signal API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── REST Endpoints ────────────────────────────────────────────────────────────


@app.get("/health")
async def health_check():
    """Health check endpoint used by Railway for liveness probes."""
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "candles_buffered": calculator.candle_count(),
        "latest_price": binance_ws.latest_price,
    }


@app.get("/api/indicators")
async def get_indicators():
    """Return the latest computed indicator snapshot."""
    snap = calculator.get_snapshot()
    if snap is None:
        raise HTTPException(status_code=503, detail="No indicator data yet. Warming up.")
    return _snapshot_to_dict(snap)


@app.get("/api/indicators/4h")
async def get_indicators_4h():
    """Return the latest 4-hour indicator snapshot (trend timeframe)."""
    snap = calculator_4h.get_snapshot()
    if snap is None:
        raise HTTPException(status_code=503, detail="4H indicators warming up.")
    d = _snapshot_to_dict(snap)
    d["candles_buffered"] = calculator_4h.candle_count()
    return d


@app.get("/api/fear-greed")
async def get_fear_greed():
    """Return the latest Fear & Greed index value.

    Served from an in-memory cache that is populated on the first news poll
    cycle (at startup).  Returns 503 while the cache is still empty.
    """
    global _latest_fear_greed  # must be declared before any use in this scope
    if _latest_fear_greed is None:
        # Cache miss — fetch live so the first page load never shows a spinner
        try:
            async with NewsFetcher() as fetcher:
                fg = await fetcher.fetch_fear_greed()
            if fg is None:
                raise HTTPException(status_code=503, detail="Fear & Greed data not yet available.")
            _latest_fear_greed = {
                "value": fg.value,
                "classification": fg.classification,
                "timestamp": fg.timestamp.isoformat(),
            }
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("Fear & Greed live fetch failed: %s", exc)
            raise HTTPException(status_code=503, detail="Fear & Greed data not yet available.")
    return _latest_fear_greed


@app.get("/api/signals/stats")
async def get_signal_stats(db: AsyncSession = Depends(get_db)):
    """Return win rate and outcome statistics for all resolved signals."""
    try:
        from sqlalchemy import select, func as sqlfunc

        result = await db.execute(
            select(
                Signal.outcome,
                sqlfunc.count(Signal.id).label("count"),
                sqlfunc.avg(Signal.pnl_percent).label("avg_pnl"),
            )
            .where(Signal.outcome.isnot(None))
            .group_by(Signal.outcome)
        )
        rows = result.all()

        stats: dict = {"wins": 0, "losses": 0, "open": 0, "win_rate_pct": 0.0, "avg_pnl_pct": 0.0}
        total_pnl = 0.0
        pnl_count = 0
        for row in rows:
            outcome, count, avg_pnl = row
            if outcome == "WIN":
                stats["wins"] = count
            elif outcome == "LOSS":
                stats["losses"] = count
            elif outcome == "OPEN":
                stats["open"] = count
            if avg_pnl is not None:
                total_pnl += float(avg_pnl) * count
                pnl_count += count

        decided = stats["wins"] + stats["losses"]
        if decided > 0:
            stats["win_rate_pct"] = round(stats["wins"] / decided * 100, 1)
        if pnl_count > 0:
            stats["avg_pnl_pct"] = round(total_pnl / pnl_count, 2)

        return stats
    except Exception as exc:
        logger.error("Failed to fetch signal stats: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch signal stats.")


@app.get("/api/signals/latest")
async def get_latest_signals(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """Return the most recent trading signals from the database."""
    try:
        from sqlalchemy import select

        stmt = (
            select(Signal)
            .order_by(Signal.generated_at.desc())
            .limit(min(limit, 100))
        )
        result = await db.execute(stmt)
        signals = result.scalars().all()
        return [_signal_to_dict(s) for s in signals]
    except Exception as exc:
        logger.error("Failed to fetch signals: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch signals.")


@app.get("/api/news")
async def get_news(
    limit: int = 30,
    db: AsyncSession = Depends(get_db),
):
    """Return recent verified news articles."""
    try:
        from sqlalchemy import select

        stmt = (
            select(NewsItem)
            .order_by(NewsItem.published_at.desc())
            .limit(min(limit, 100))
        )
        result = await db.execute(stmt)
        items = result.scalars().all()
        return [_news_to_dict(n) for n in items]
    except Exception as exc:
        logger.error("Failed to fetch news: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch news.")


@app.get("/api/alerts/history")
async def get_alert_history(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """Return the alert history log."""
    try:
        from sqlalchemy import select

        stmt = (
            select(Alert)
            .order_by(Alert.triggered_at.desc())
            .limit(min(limit, 200))
        )
        result = await db.execute(stmt)
        alerts = result.scalars().all()
        return [_alert_to_dict(a) for a in alerts]
    except Exception as exc:
        logger.error("Failed to fetch alerts: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch alerts.")


@app.post("/api/levels")
async def set_key_levels(levels: list[float]):
    """
    Set key support/resistance price levels for proximity alerts.

    The alert manager will notify when BTC comes within 1% of any level.
    """
    global _key_levels
    _key_levels = sorted(set(levels))
    logger.info("Key levels updated: %s", _key_levels)
    return {"levels": _key_levels, "count": len(_key_levels)}


@app.get("/api/levels")
async def get_key_levels():
    """Return the current set of key price levels."""
    return {"levels": _key_levels}


@app.get("/api/backtest")
async def run_backtest(days: int = 30, db: AsyncSession = Depends(get_db)):
    """
    Run a backtest over the last N days of stored candles.

    Returns aggregated performance statistics.
    """
    if days < 1 or days > 180:
        raise HTTPException(status_code=400, detail="days must be between 1 and 180.")

    try:
        import pandas as pd
        from sqlalchemy import select
        from datetime import timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        stmt = (
            select(PriceCandle)
            .where(PriceCandle.open_time >= cutoff)
            .order_by(PriceCandle.open_time.asc())
        )
        result = await db.execute(stmt)
        candles = result.scalars().all()

        if not candles:
            raise HTTPException(
                status_code=404, detail=f"No candles found for the last {days} days."
            )

        df = pd.DataFrame(
            [
                {
                    "timestamp": c.open_time,
                    "open": float(c.open_price),
                    "high": float(c.high_price),
                    "low": float(c.low_price),
                    "close": float(c.close_price),
                    "volume": float(c.volume),
                }
                for c in candles
            ]
        ).set_index("timestamp")

        engine = BacktestEngine()
        backtest_result = engine.run(df)
        return {**backtest_result.to_dict(), "candles_used": len(df)}

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Backtest failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Backtest failed.")


# ── WebSocket Endpoint ────────────────────────────────────────────────────────


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Real-time WebSocket feed.

    Clients receive JSON messages of type:
      - price_tick   → every best-ask update from Binance
      - indicators   → snapshot on each candle close
      - signal       → when a signal is generated
      - alert        → when an alert fires
      - news         → when new articles are fetched
    """
    await websocket.accept()
    alert_manager.ws_broadcaster.add_client(websocket)
    logger.info("WebSocket client connected.")

    try:
        # Send current state immediately on connect
        snap = calculator.get_snapshot()
        if snap:
            await websocket.send_text(
                json.dumps({"type": "indicators", **_snapshot_to_dict(snap)})
            )
        if binance_ws.latest_price:
            await websocket.send_text(
                json.dumps({"type": "price_tick", "price": binance_ws.latest_price})
            )

        # Keep connection alive — actual messages are pushed by the broadcaster
        while True:
            await asyncio.sleep(30)
            await websocket.send_text(json.dumps({"type": "ping"}))
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected.")
    except Exception as exc:
        logger.error("WebSocket error: %s", exc)
    finally:
        alert_manager.ws_broadcaster.remove_client(websocket)


# ── Background task callbacks ─────────────────────────────────────────────────


def _get_4h_trend_direction() -> int:
    """
    Derive the 4-hour trend direction from the 4H IndicatorCalculator.

    Returns +1 (bullish), -1 (bearish), or 0 (neutral/insufficient data).

    Logic: uses the same EMA alignment and RSI checks as the 1M engine but
    on 4H data.  The 4H trend must agree with a 1M signal before it fires.

      Bullish  (+1): price > EMA20 > EMA50  AND  RSI < 70
      Bearish  (-1): price < EMA20 < EMA50  AND  RSI > 30
      Neutral   (0): mixed or insufficient data
    """
    snap = calculator_4h.get_snapshot()
    if snap is None or snap.close_price is None:
        return 0

    p = snap.close_price
    e20 = snap.ema_20
    e50 = snap.ema_50
    rsi = snap.rsi_14

    if None in (e20, e50):
        return 0

    if p > e20 > e50 and (rsi is None or rsi < 70):
        return +1
    if p < e20 < e50 and (rsi is None or rsi > 30):
        return -1
    return 0


async def _on_candle_closed(candle: Candle, snapshot: IndicatorSnapshot) -> None:
    """
    Called by BinanceWebSocketClient on every closed 1-minute candle.

    Actions:
      1. Broadcast indicators to WS clients
      2. Persist candle + indicators to DB
      3. Evaluate signal engine with dual-timeframe gate
      4. Check key level proximity
    """
    # Broadcast 1M indicator update to all WS clients
    try:
        snap_dict = _snapshot_to_dict(snapshot)
        snap_dict["type"] = "indicators"
        await alert_manager.ws_broadcaster.broadcast(snap_dict)
    except Exception as exc:
        logger.error("Failed to broadcast indicators: %s", exc)

    # Persist to DB
    await _persist_candle(candle, snapshot)

    # ── Dual-timeframe signal gate ──────────────────────────────────────
    # Step 1: evaluate 1M signal (entry timing)
    signal = signal_engine.evaluate(snapshot, candle_count=calculator.candle_count())

    if signal:
        signal_is_bullish = signal.signal_type.value in ("BUY", "STRONG_BUY")
        signal_is_bearish = signal.signal_type.value in ("SELL", "STRONG_SELL")

        # Step 2: check 4H trend direction agrees with the 1M signal
        trend = _get_4h_trend_direction()
        trend_confirms = (
            (signal_is_bullish and trend == +1) or
            (signal_is_bearish and trend == -1) or
            trend == 0  # no 4H data yet → don't block
        )

        # Step 3: Fear & Greed macro filter
        #   BUY  signals only when F&G < 40 (fear zone — market oversold at macro level)
        #   SELL signals only when F&G > 60 (greed zone — market overextended)
        #   HOLD signals pass through always
        fg_value = _latest_fear_greed.get("value") if _latest_fear_greed else None
        fg_allows = True
        if fg_value is not None:
            if signal_is_bullish and fg_value >= 40:
                fg_allows = False
                logger.info(
                    "BUY signal blocked: Fear & Greed=%d (need < 40 for BUY)", fg_value
                )
            elif signal_is_bearish and fg_value <= 60:
                fg_allows = False
                logger.info(
                    "SELL signal blocked: Fear & Greed=%d (need > 60 for SELL)", fg_value
                )

        if trend_confirms and fg_allows:
            signal_id = await _persist_signal(signal)
            await alert_manager.fire_signal_alert(signal)
            sig_dict = {
                **signal.to_dict(),
                "type": "signal",
                "trend_4h": trend,
                "fear_greed": fg_value,
            }
            await alert_manager.ws_broadcaster.broadcast(sig_dict)
            logger.info(
                "Signal fired: %s conf=%.1f%% 4H_trend=%+d F&G=%s",
                signal.signal_type.value, signal.confidence, trend, fg_value,
            )
        elif not trend_confirms:
            logger.info(
                "1M signal %s blocked: 4H trend=%+d disagrees",
                signal.signal_type.value, trend,
            )

    # Check key level proximity
    if snapshot.close_price and _key_levels:
        for level in _key_levels:
            await alert_manager.fire_price_level_alert(snapshot.close_price, level)


async def _on_price_tick(data: dict) -> None:
    """
    Called on every bookTicker event.

    Broadcasts live best-ask price to all WS clients.
    """
    try:
        price = float(data.get("a", 0) or data.get("p", 0))
        if price > 0:
            await alert_manager.ws_broadcaster.broadcast(
                {"type": "price_tick", "price": price, "bid": data.get("b"), "ask": data.get("a")}
            )
    except Exception as exc:
        logger.debug("Price tick broadcast error: %s", exc)


async def _price_fallback_loop() -> None:
    """Poll Coinbase spot price every 10s when Binance WebSocket is geo-blocked."""
    import httpx

    while True:
        try:
            await asyncio.sleep(10)
            if binance_ws.latest_price is not None:
                continue
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get("https://api.coinbase.com/v2/prices/BTC-USD/spot")
                resp.raise_for_status()
                price = float(resp.json()["data"]["amount"])
            binance_ws.update_latest_price(price)
            await alert_manager.ws_broadcaster.broadcast(
                {"type": "price_tick", "price": price, "source": "coinbase_fallback"}
            )
            logger.info("Price fallback delivered BTC/USD: %.2f", price)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.debug("Price fallback poll failed: %s", exc)


async def _outcome_check_loop() -> None:
    """Background loop: every 5 minutes resolve WIN/LOSS for signals older than 4 hours."""
    while True:
        try:
            await _resolve_signal_outcomes()
            await asyncio.sleep(300)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("Outcome check loop error: %s", exc)
            await asyncio.sleep(60)


async def _resolve_signal_outcomes() -> None:
    """
    For each signal with no outcome that was generated >= 4 hours ago,
    scan the stored candles to see if TP or SL was hit first.

    BUY/STRONG_BUY: WIN if any candle.high >= take_profit
                    LOSS if any candle.low  <= stop_loss
    SELL/STRONG_SELL: WIN if any candle.low  <= take_profit
                      LOSS if any candle.high >= stop_loss

    If neither level was touched in 4 hours → mark OPEN (timed out).
    """
    from datetime import timedelta
    from sqlalchemy import select, and_

    EVALUATION_WINDOW_H = 4

    try:
        async with AsyncSessionLocal() as session:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=EVALUATION_WINDOW_H)
            result = await session.execute(
                select(Signal).where(
                    and_(
                        Signal.outcome.is_(None),
                        Signal.generated_at <= cutoff,
                        Signal.take_profit.isnot(None),
                        Signal.stop_loss.isnot(None),
                    )
                )
            )
            pending = result.scalars().all()

            if not pending:
                return

            for sig in pending:
                window_end = sig.generated_at + timedelta(hours=EVALUATION_WINDOW_H)
                candle_result = await session.execute(
                    select(PriceCandle)
                    .where(
                        and_(
                            PriceCandle.open_time >= sig.generated_at,
                            PriceCandle.open_time <= window_end,
                        )
                    )
                    .order_by(PriceCandle.open_time.asc())
                )
                candles = candle_result.scalars().all()

                outcome = "OPEN"
                outcome_price = None
                outcome_at = None

                is_long = sig.signal_type in ("BUY", "STRONG_BUY")

                for c in candles:
                    h = float(c.high_price)
                    lo = float(c.low_price)
                    tp = float(sig.take_profit)
                    sl = float(sig.stop_loss)

                    if is_long:
                        if h >= tp:
                            outcome, outcome_price, outcome_at = "WIN", tp, c.open_time
                            break
                        if lo <= sl:
                            outcome, outcome_price, outcome_at = "LOSS", sl, c.open_time
                            break
                    else:  # SHORT
                        if lo <= tp:
                            outcome, outcome_price, outcome_at = "WIN", tp, c.open_time
                            break
                        if h >= sl:
                            outcome, outcome_price, outcome_at = "LOSS", sl, c.open_time
                            break

                entry = float(sig.entry_price)
                if outcome_price and entry:
                    if is_long:
                        pnl = (outcome_price - entry) / entry * 100
                    else:
                        pnl = (entry - outcome_price) / entry * 100
                else:
                    pnl = None

                sig.outcome = outcome
                sig.outcome_price = outcome_price
                sig.outcome_at = outcome_at or datetime.now(timezone.utc)
                sig.pnl_percent = round(pnl, 4) if pnl is not None else None

                logger.info(
                    "Signal %d resolved: %s (pnl=%.2f%%)", sig.id, outcome, pnl or 0
                )

            await session.commit()
            logger.info("Resolved outcomes for %d signal(s)", len(pending))

    except Exception as exc:
        logger.error("Signal outcome resolution failed: %s", exc, exc_info=True)


async def _news_poll_loop() -> None:
    """Background loop: fetch news every 15 minutes."""
    while True:
        try:
            await _fetch_and_process_news()
            await asyncio.sleep(NEWS_POLL_INTERVAL_S)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("News poll loop error: %s", exc)
            await asyncio.sleep(60)


async def _fetch_and_process_news() -> None:
    """Fetch, filter, analyse, persist, and alert on new news articles."""
    try:
        async with NewsFetcher() as fetcher:
            articles = await fetcher.fetch_all_news()
            fear_greed = await fetcher.fetch_fear_greed()
            liquidations = await fetcher.fetch_coinglass_liquidations()

        if not articles:
            logger.debug("No articles fetched this cycle.")

        # Quality badge (cross-reference) — never blocks publication
        decisions = fake_news_filter.evaluate_batch(articles) if articles else []

        # Process each article
        async with AsyncSessionLocal() as session:
            for article, decision in zip(articles, decisions):
                sentiment_result = sentiment_analyzer.analyse(
                    article.title, article.summary
                )

                news_item = NewsItem(
                    source=article.source,
                    title=article.title,
                    url=article.url,
                    published_at=article.published_at,
                    sentiment=sentiment_result.sentiment.value,
                    sentiment_score=sentiment_result.score,
                    is_geopolitical=sentiment_result.is_geopolitical,
                    geo_keywords=",".join(sentiment_result.geo_keywords_found),
                    is_filtered=decision.is_filtered,
                    cross_referenced=decision.cross_referenced,
                )

                # Use merge to handle duplicate URLs gracefully
                from sqlalchemy.dialects.postgresql import insert as pg_insert

                stmt = (
                    pg_insert(NewsItem)
                    .values(
                        source=news_item.source,
                        title=news_item.title,
                        url=news_item.url,
                        published_at=news_item.published_at,
                        sentiment=news_item.sentiment,
                        sentiment_score=news_item.sentiment_score,
                        is_geopolitical=news_item.is_geopolitical,
                        geo_keywords=news_item.geo_keywords,
                        is_filtered=news_item.is_filtered,
                        cross_referenced=news_item.cross_referenced,
                    )
                    .on_conflict_do_update(
                        index_elements=["url"],
                        set_={
                            # Re-evaluate filter decision on every fetch so
                            # articles previously blocked as unverified can
                            # be unblocked when the filter logic improves.
                            "is_filtered": news_item.is_filtered,
                            "cross_referenced": news_item.cross_referenced,
                            "sentiment": news_item.sentiment,
                            "sentiment_score": news_item.sentiment_score,
                        },
                    )
                )
                await session.execute(stmt)

                # Alert on high-impact articles (quality badge shown via cross_referenced)
                if sentiment_result.is_geopolitical or sentiment_result.sentiment.value != "NEUTRAL":
                    await alert_manager.fire_news_alert(
                        title=article.title,
                        source=article.source,
                        sentiment=sentiment_result.sentiment.value,
                    )
                    # Broadcast news to WS
                    await alert_manager.ws_broadcaster.broadcast(
                        {
                            "type": "news",
                            "title": article.title,
                            "source": article.source,
                            "sentiment": sentiment_result.sentiment.value,
                            "score": sentiment_result.score,
                            "is_geopolitical": sentiment_result.is_geopolitical,
                            "cross_referenced": decision.cross_referenced,
                        }
                    )

            if articles:
                await session.commit()

        # Liquidation alert
        if liquidations:
            await alert_manager.fire_liquidation_alert(
                total_usd=liquidations.total_liquidations_usd,
                long_usd=liquidations.long_liquidations_usd,
                short_usd=liquidations.short_liquidations_usd,
            )

        # Cache and broadcast Fear & Greed
        if fear_greed:
            global _latest_fear_greed
            _latest_fear_greed = {
                "value": fear_greed.value,
                "classification": fear_greed.classification,
                "timestamp": fear_greed.timestamp.isoformat(),
            }
            await alert_manager.ws_broadcaster.broadcast(
                {"type": "fear_greed", **_latest_fear_greed}
            )

    except Exception as exc:
        logger.error("News processing error: %s", exc, exc_info=True)


# ── DB persistence helpers ────────────────────────────────────────────────────


async def _persist_candle(candle: Candle, snapshot: IndicatorSnapshot) -> None:
    """Upsert a candle and its indicator snapshot into the database."""
    try:
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        async with AsyncSessionLocal() as session:
            # Upsert candle
            candle_stmt = (
                pg_insert(PriceCandle)
                .values(
                    open_time=candle.timestamp,
                    open_price=candle.open,
                    high_price=candle.high,
                    low_price=candle.low,
                    close_price=candle.close,
                    volume=candle.volume,
                    close_time=candle.timestamp,
                    quote_asset_volume=0,
                    number_of_trades=0,
                    taker_buy_base_volume=0,
                    taker_buy_quote_volume=0,
                )
                .on_conflict_do_nothing(index_elements=["open_time"])
            )
            await session.execute(candle_stmt)

            # Upsert indicators
            ind_stmt = (
                pg_insert(TechnicalIndicator)
                .values(
                    candle_time=candle.timestamp,
                    rsi_14=snapshot.rsi_14,
                    macd_line=snapshot.macd_line,
                    macd_signal=snapshot.macd_signal,
                    macd_histogram=snapshot.macd_histogram,
                    ema_20=snapshot.ema_20,
                    ema_50=snapshot.ema_50,
                    ema_200=snapshot.ema_200,
                    bb_upper=snapshot.bb_upper,
                    bb_middle=snapshot.bb_middle,
                    bb_lower=snapshot.bb_lower,
                    bb_percent_b=snapshot.bb_percent_b,
                    volume_sma_20=snapshot.volume_sma_20,
                    volume_ratio=snapshot.volume_ratio,
                )
                .on_conflict_do_nothing(index_elements=["candle_time"])
            )
            await session.execute(ind_stmt)
            await session.commit()

    except Exception as exc:
        logger.error("Failed to persist candle/indicators: %s", exc)


async def _persist_signal(signal: SignalResult) -> Optional[int]:
    """Persist a signal to the database. Returns the new row's ID."""
    try:
        async with AsyncSessionLocal() as session:
            db_signal = Signal(
                signal_type=signal.signal_type.value,
                confidence=signal.confidence,
                entry_price=signal.entry_price,
                take_profit=signal.take_profit,
                stop_loss=signal.stop_loss,
                risk_reward_ratio=signal.risk_reward_ratio,
                indicators_agreed=signal.indicators_agreed,
                indicator_details=signal.indicator_details,
            )
            session.add(db_signal)
            await session.flush()
            signal_id = db_signal.id
            await session.commit()
            return signal_id
    except Exception as exc:
        logger.error("Failed to persist signal: %s", exc)
        return None


# ── Serialisation helpers ─────────────────────────────────────────────────────


def _snapshot_to_dict(snap: IndicatorSnapshot) -> dict:
    return {
        "timestamp": snap.timestamp.isoformat() if snap.timestamp else None,
        "close_price": snap.close_price,
        "rsi_14": snap.rsi_14,
        "macd_line": snap.macd_line,
        "macd_signal": snap.macd_signal,
        "macd_histogram": snap.macd_histogram,
        "ema_20": snap.ema_20,
        "ema_50": snap.ema_50,
        "ema_200": snap.ema_200,
        "bb_upper": snap.bb_upper,
        "bb_middle": snap.bb_middle,
        "bb_lower": snap.bb_lower,
        "bb_percent_b": snap.bb_percent_b,
        "volume_sma_20": snap.volume_sma_20,
        "volume_ratio": snap.volume_ratio,
    }


def _signal_to_dict(s: Signal) -> dict:
    return {
        "id": s.id,
        "signal_type": s.signal_type,
        "confidence": s.confidence,
        "entry_price": float(s.entry_price),
        "take_profit": float(s.take_profit) if s.take_profit else None,
        "stop_loss": float(s.stop_loss) if s.stop_loss else None,
        "risk_reward_ratio": s.risk_reward_ratio,
        "indicators_agreed": s.indicators_agreed,
        "generated_at": s.generated_at.isoformat(),
        "outcome": s.outcome,
        "pnl_percent": s.pnl_percent,
    }


def _news_to_dict(n: NewsItem) -> dict:
    return {
        "id": n.id,
        "source": n.source,
        "title": n.title,
        "url": n.url,
        "published_at": n.published_at.isoformat() if n.published_at else None,
        "sentiment": n.sentiment,
        "sentiment_score": n.sentiment_score,
        "is_geopolitical": n.is_geopolitical,
        "geo_keywords": n.geo_keywords,
        "cross_referenced": n.cross_referenced,
    }


def _alert_to_dict(a: Alert) -> dict:
    return {
        "id": a.id,
        "alert_type": a.alert_type,
        "message": a.message,
        "triggered_at": a.triggered_at.isoformat(),
        "is_sent": a.is_sent,
    }


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=not settings.is_production,
        log_level="debug" if not settings.is_production else "info",
    )
