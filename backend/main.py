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
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from alerts.manager import AlertManager, AlertType
from config import settings
from database.candle_backfill import backfill_1m_candles
from database.connection import AsyncSessionLocal, get_db, init_db
from database.models import Alert, NewsItem, PriceCandle, Signal, TechnicalIndicator
from indicators.binance_ws import BinanceWebSocketClient
from indicators.calculator import Candle, IndicatorCalculator, IndicatorSnapshot
from news.fetcher import FEAR_GREED_POLL_INTERVAL_S, NEWS_POLL_INTERVAL_S, NewsFetcher
from news.filter import FakeNewsFilter
from news.sentiment import SentimentAnalyzer
from signals.backtester import BacktestEngine, BacktestOptions
from signals.engine import SignalEngine, SignalResult
from signals.param_sweep import run_param_sweep, run_quality_sweep

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

# Latest Fear & Greed snapshot — refreshed hourly by _fear_greed_poll_loop.
_latest_fear_greed: Optional[dict] = None
_fear_greed_poll_task: Optional[asyncio.Task] = None
FEAR_GREED_STALE_SECONDS = 70 * 60  # poll alive if updated within 70 min

# 4H candle periodic refresh — REST safety net; live updates come from kline_4h WS.
_4h_last_refreshed: Optional[datetime] = None
_4H_REFRESH_INTERVAL_S = 300  # 5 minutes (backup resync only)

# Research param-sweep job state (in-memory, single process)
_sweep_task: Optional[asyncio.Task] = None
_sweep_result: Optional[dict] = None
_sweep_error: Optional[str] = None
_sweep_running = False

# Research single-backtest job state — separate from the sweep job so a
# long single backtest (e.g. 60-90 day windows) doesn't collide with sweeps.
_backtest_job_task: Optional[asyncio.Task] = None
_backtest_job_result: Optional[dict] = None
_backtest_job_error: Optional[str] = None
_backtest_job_running = False

# Startup / status tracking
_startup_ready = False
_app_start_time = time.time()
_db_connected = False
_last_news_fetch: Optional[datetime] = None
_news_count = 0
_last_signal_at: Optional[datetime] = None


# ── Application lifespan ──────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events."""
    global _startup_ready, _db_connected, _latest_fear_greed
    global _last_news_fetch, _news_count, _4h_last_refreshed

    logger.info("BTC Signal Pro starting up...")

    # 1. Connect database
    try:
        await init_db()
        _db_connected = True
        logger.info("Database connected.")
    except Exception as exc:
        _db_connected = False
        logger.error("DB init failed — running without persistence: %s", exc)

    # 2. Preload 300 × 1M candles
    loaded_1m = await binance_ws.preload_historical_candles(limit=300)
    logger.info("Preloaded %d × 1M candles", loaded_1m)

    # 3. Preload 200 × 4H candles
    loaded_4h = await binance_ws.preload_4h_candles(limit=200)
    logger.info("Preloaded %d × 4H candles", loaded_4h)
    _4h_last_refreshed = datetime.now(timezone.utc)

    # 4. Fetch Fear & Greed immediately on startup
    await _refresh_fear_greed()

    # 5. Fetch news (wait)
    await _fetch_and_process_news()

    # Register WebSocket callbacks
    binance_ws.on_candle_closed(_on_candle_closed)
    binance_ws.on_4h_candle_closed(_on_4h_candle_closed)
    binance_ws.on_price_tick(_on_price_tick)

    # 6. Start Binance WebSocket (preload already done above)
    ws_task = asyncio.create_task(binance_ws.run(skip_preload=True), name="binance-ws")

    # 7. Signal engine is ready (evaluate() runs on each closed candle)
    logger.info("Signal engine ready.")

    # 8. Start background loops
    news_task = asyncio.create_task(_news_poll_loop(), name="news-poll")
    global _fear_greed_poll_task
    _fear_greed_poll_task = asyncio.create_task(
        _fear_greed_poll_loop(), name="fear-greed-poll"
    )
    fear_greed_task = _fear_greed_poll_task
    logger.info(
        "F&G poll task scheduled (done=%s, cancelled=%s)",
        _fear_greed_poll_task.done(),
        _fear_greed_poll_task.cancelled(),
    )
    refresh_4h_task = asyncio.create_task(_4h_refresh_loop(), name="4h-refresh")
    fallback_task = asyncio.create_task(_price_fallback_loop(), name="price-fallback")
    outcome_task = asyncio.create_task(_outcome_check_loop(), name="outcome-check")

    _startup_ready = True
    logger.info(
        "BTC Signal Pro ready. Listening on %s:%d",
        settings.APP_HOST,
        settings.APP_PORT,
    )

    yield  # application runs here

    # Graceful shutdown
    logger.info("Shutting down...")
    _startup_ready = False
    await binance_ws.stop()
    ws_task.cancel()
    news_task.cancel()
    fear_greed_task.cancel()
    refresh_4h_task.cancel()
    fallback_task.cancel()
    outcome_task.cancel()
    try:
        await asyncio.gather(
            ws_task, news_task, fear_greed_task, refresh_4h_task,
            fallback_task, outcome_task,
            return_exceptions=True,
        )
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
    if not _startup_ready:
        raise HTTPException(status_code=503, detail="Service is starting up.")
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "candles_buffered": calculator.candle_count(),
        "latest_price": binance_ws.latest_price,
    }


@app.get("/api/status")
async def get_system_status(db: AsyncSession = Depends(get_db)):
    """Return a full operational health snapshot for the dashboard status bar."""
    last_signal_iso = _last_signal_at.isoformat() if _last_signal_at else None
    if last_signal_iso is None and _db_connected:
        try:
            from sqlalchemy import select

            result = await db.execute(
                select(Signal).order_by(Signal.generated_at.desc()).limit(1)
            )
            sig = result.scalar_one_or_none()
            if sig:
                last_signal_iso = sig.generated_at.isoformat()
        except Exception as exc:
            logger.debug("Could not fetch last signal for status: %s", exc)

    fg_updated = (
        _latest_fear_greed.get("updated_at") if _latest_fear_greed else None
    )

    return {
        "candles_1m": calculator.candle_count(),
        "candles_4h": calculator_4h.candle_count(),
        "4h_last_refreshed": _4h_last_refreshed.isoformat() if _4h_last_refreshed else None,
        "last_news_fetch": _last_news_fetch.isoformat() if _last_news_fetch else None,
        "news_count": _news_count,
        "fear_greed": _latest_fear_greed.get("value") if _latest_fear_greed else None,
        "fear_greed_updated": fg_updated,
        "fear_greed_poll_alive": _fear_greed_poll_alive(),
        "ws_connected": binance_ws.ws_connected,
        "ws_last_message_seconds": binance_ws.ws_last_message_seconds,
        "last_signal": last_signal_iso,
        "db_connected": _db_connected,
        "uptime_seconds": int(time.time() - _app_start_time),
        "startup_ready": _startup_ready,
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

    Served from an in-memory cache refreshed hourly by a dedicated poll loop.
    Returns 503 while the cache is still empty.
    """
    global _latest_fear_greed  # must be declared before any use in this scope
    if _latest_fear_greed is None:
        await _refresh_fear_greed()
        if _latest_fear_greed is None:
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


@app.post("/api/admin/backfill-1m")
async def admin_backfill_1m(days: int = 30, db: AsyncSession = Depends(get_db)):
    """Backfill historical 1M candles from Binance REST into PostgreSQL."""
    if days < 1 or days > 90:
        raise HTTPException(status_code=400, detail="days must be between 1 and 90.")
    try:
        return await backfill_1m_candles(db, days=days)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("1M candle backfill failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="1M candle backfill failed.")


@app.post("/api/admin/refresh-4h")
async def admin_refresh_4h():
    """Manually trigger a 4H REST resync (WebSocket delivers closes in real time)."""
    ok = await _refresh_4h_candles()
    if not ok:
        raise HTTPException(status_code=503, detail="4H candle refresh failed.")
    snap = calculator_4h.get_snapshot()
    return {
        "refreshed": True,
        "4h_last_refreshed": _4h_last_refreshed.isoformat() if _4h_last_refreshed else None,
        "candles_4h": calculator_4h.candle_count(),
        "latest_close": snap.close_price if snap else None,
        "latest_timestamp": snap.timestamp.isoformat() if snap and snap.timestamp else None,
    }


@app.post("/api/admin/quick-sweep")
async def admin_quick_sweep(
    days: int = 30,
    taker_fee_pct: float = 0.04,
    async_run: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Run all 7 quality scenarios in one server-side pass.

    With ``async_run=true`` (recommended on Railway) returns immediately;
    poll ``GET /api/admin/param-sweep/status`` for results (~3-5 min compute).
    """
    global _sweep_task, _sweep_running, _sweep_result, _sweep_error
    if days < 1 or days > 90:
        raise HTTPException(status_code=400, detail="days must be between 1 and 90.")
    if async_run:
        if _sweep_running:
            return {"status": "running", "poll": "/api/admin/param-sweep/status"}
        _sweep_result = None
        _sweep_error = None
        _sweep_running = True

        async def _job() -> None:
            global _sweep_result, _sweep_error, _sweep_running
            try:
                async with AsyncSessionLocal() as session:
                    frames = await _load_backtest_frames(days, session)
                loop = asyncio.get_running_loop()
                _sweep_result = await loop.run_in_executor(
                    None,
                    lambda: run_quality_sweep(
                        frames["df"],
                        frames["df_4h"],
                        frames["fg_history"],
                        days=days,
                        fee_pct=taker_fee_pct,
                    ),
                )
            except Exception as exc:
                logger.error("Background quick sweep failed: %s", exc, exc_info=True)
                _sweep_error = str(exc)
            finally:
                _sweep_running = False

        _sweep_task = asyncio.create_task(_job(), name="quick-sweep")
        return {"status": "started", "poll": "/api/admin/param-sweep/status"}

    try:
        frames = await _load_backtest_frames(days, db)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: run_quality_sweep(
                frames["df"],
                frames["df_4h"],
                frames["fg_history"],
                days=days,
                fee_pct=taker_fee_pct,
            ),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Quick sweep failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Quick sweep failed.")


@app.post("/api/admin/param-sweep")
async def admin_param_sweep(
    days: int = 30,
    taker_fee_pct: float = 0.04,
    isolated_only: bool = False,
    combos_only: bool = False,
    async_run: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """Research-only parameter sweep over stored candles (not live trading).

    When ``async_run=true`` (default) the sweep runs in a background task;
    poll ``GET /api/admin/param-sweep/status`` for results.
    """
    global _sweep_task, _sweep_running, _sweep_result, _sweep_error
    if days < 1 or days > 90:
        raise HTTPException(status_code=400, detail="days must be between 1 and 90.")
    if isolated_only and combos_only:
        raise HTTPException(
            status_code=400,
            detail="Use isolated_only or combos_only, not both.",
        )
    if async_run:
        if _sweep_running:
            return {"status": "running", "message": "Sweep already in progress."}
        _sweep_result = None
        _sweep_error = None
        _sweep_running = True

        async def _job() -> None:
            global _sweep_result, _sweep_error, _sweep_running
            try:
                async with AsyncSessionLocal() as session:
                    frames = await _load_backtest_frames(days, session)
                loop = asyncio.get_running_loop()
                _sweep_result = await loop.run_in_executor(
                    None,
                    lambda: run_param_sweep(
                        frames["df"],
                        frames["df_4h"],
                        frames["fg_history"],
                        days=days,
                        fee_pct=taker_fee_pct,
                        isolated_only=isolated_only,
                        combos_only=combos_only,
                    ),
                )
            except Exception as exc:
                logger.error("Background param sweep failed: %s", exc, exc_info=True)
                _sweep_error = str(exc)
            finally:
                _sweep_running = False

        _sweep_task = asyncio.create_task(_job(), name="param-sweep")
        return {"status": "started", "poll": "/api/admin/param-sweep/status"}

    try:
        frames = await _load_backtest_frames(days, db)
        return run_param_sweep(
            frames["df"],
            frames["df_4h"],
            frames["fg_history"],
            days=days,
            fee_pct=taker_fee_pct,
            isolated_only=isolated_only,
            combos_only=combos_only,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Param sweep failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Param sweep failed.")


@app.get("/api/admin/param-sweep/status")
async def admin_param_sweep_status():
    """Poll background param-sweep job status and results."""
    if _sweep_running:
        return {"status": "running"}
    if _sweep_error:
        return {"status": "error", "error": _sweep_error}
    if _sweep_result:
        return {"status": "complete", "result": _sweep_result}
    return {"status": "idle"}


async def _run_backtest_core(days: int, db: AsyncSession, options: BacktestOptions, gate_mode: str) -> dict:
    frames = await _load_backtest_frames(days, db)
    df = frames["df"]
    df_4h = frames["df_4h"]
    fg_history = frames["fg_history"]

    loop = asyncio.get_running_loop()
    backtest_result = await loop.run_in_executor(
        None,
        lambda: BacktestEngine().run(
            df, df_4h=df_4h, fg_history=fg_history, options=options
        ),
    )
    return {
        **backtest_result.to_dict(),
        "candles_used": len(df),
        "4h_candles_used": len(df_4h) if df_4h is not None else 0,
        "fg_days_used": len(fg_history) if fg_history else 0,
        "gate_mode": gate_mode,
        "confidence_threshold": options.confidence_threshold,
        "min_indicators": options.min_indicators,
        "min_tp_pct": options.min_tp_pct,
        "min_sl_pct": options.min_sl_pct,
        "sequential_only": options.sequential_only,
        "min_atr_pct": options.min_atr_pct,
        "use_trailing_exit": options.use_trailing_exit,
    }


@app.get("/api/backtest")
async def run_backtest(
    days: int = 30,
    taker_fee_pct: float = 0.0,
    gate_mode: str = "full",
    confidence_threshold: float = 70.0,
    min_indicators: int = 3,
    min_tp_pct: float = 0.005,
    min_sl_pct: float = 0.003,
    sequential_only: bool = False,
    min_atr_pct: Optional[float] = None,
    use_trailing_exit: bool = False,
    trailing_activation_pct: float = 0.004,
    trailing_distance_pct: float = 0.003,
    trailing_max_hold_bars: int = 180,
    async_run: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """
    Run a backtest over the last N days of stored candles.

    Returns 1M-only and gated metrics. Research params do not affect live engine.

    sequential_only=true enforces one open position at a time (skips any
    signal that fires while a prior trade hasn't hit TP/SL/timeout yet) —
    research-only opportunity-cost analysis of overtrading vs fees.

    min_atr_pct sets a volatility regime filter (skip signals when
    ATR/price is below this ratio — avoids trading dead-flat chop).

    use_trailing_exit replaces the fixed take-profit with a trailing stop
    that only activates after a favorable move ("let winners run").

    async_run=true (recommended for windows beyond ~30-45 days, which can
    exceed Railway's ~5min proxy timeout) returns immediately; poll
    GET /api/admin/backtest/status for the result.
    """
    global _backtest_job_task, _backtest_job_running, _backtest_job_result, _backtest_job_error

    if days < 1 or days > 180:
        raise HTTPException(status_code=400, detail="days must be between 1 and 180.")
    if gate_mode not in ("full", "4h_only", "fg_only", "none"):
        raise HTTPException(status_code=400, detail="Invalid gate_mode.")

    options = BacktestOptions(
        taker_fee_pct=taker_fee_pct,
        gate_mode=gate_mode,  # type: ignore[arg-type]
        confidence_threshold=confidence_threshold,
        min_indicators=min_indicators,
        min_tp_pct=min_tp_pct,
        min_sl_pct=min_sl_pct,
        sequential_only=sequential_only,
        min_atr_pct=min_atr_pct,
        use_trailing_exit=use_trailing_exit,
        trailing_activation_pct=trailing_activation_pct,
        trailing_distance_pct=trailing_distance_pct,
        trailing_max_hold_bars=trailing_max_hold_bars,
    )

    if async_run:
        if _backtest_job_running:
            return {"status": "running", "poll": "/api/admin/backtest/status"}
        _backtest_job_result = None
        _backtest_job_error = None
        _backtest_job_running = True

        async def _job() -> None:
            global _backtest_job_result, _backtest_job_error, _backtest_job_running
            try:
                async with AsyncSessionLocal() as session:
                    _backtest_job_result = await _run_backtest_core(days, session, options, gate_mode)
            except Exception as exc:
                logger.error("Background backtest failed: %s", exc, exc_info=True)
                _backtest_job_error = str(exc)
            finally:
                _backtest_job_running = False

        _backtest_job_task = asyncio.create_task(_job(), name="backtest")
        return {"status": "started", "poll": "/api/admin/backtest/status"}

    try:
        return await _run_backtest_core(days, db, options, gate_mode)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Backtest failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Backtest failed.")


@app.get("/api/admin/backtest/status")
async def admin_backtest_status():
    """Poll background single-backtest job status and result."""
    if _backtest_job_running:
        return {"status": "running"}
    if _backtest_job_error:
        return {"status": "error", "error": _backtest_job_error}
    if _backtest_job_result:
        return {"status": "complete", "result": _backtest_job_result}
    return {"status": "idle"}


@app.get("/api/backtest/deadzone")
async def run_deadzone_analysis(
    days: int = 30,
    taker_fee_pct: float = 0.04,
    db: AsyncSession = Depends(get_db),
):
    """Research: count 1M signals during gate-deadlock regimes and ungated win rate."""
    if days < 1 or days > 180:
        raise HTTPException(status_code=400, detail="days must be between 1 and 180.")

    try:
        frames = await _load_backtest_frames(days, db)
        df = frames["df"]
        df_4h = frames["df_4h"]
        fg_history = frames["fg_history"]

        if df_4h is None or df_4h.empty:
            raise HTTPException(status_code=503, detail="4H candle data unavailable.")
        if not fg_history:
            raise HTTPException(status_code=503, detail="Fear & Greed history unavailable.")

        options = BacktestOptions(taker_fee_pct=taker_fee_pct)
        loop = asyncio.get_running_loop()
        engine = BacktestEngine()

        def _analyze() -> dict:
            _, signals = engine.collect_signals(df, options)
            report = engine.analyze_deadzone_opportunity(
                df, signals, df_4h, fg_history, options=options
            )
            report["days"] = days
            report["candles_used"] = len(df)
            report["4h_candles_used"] = len(df_4h)
            report["fg_days_used"] = len(fg_history)
            return report

        return await loop.run_in_executor(None, _analyze)

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Dead-zone analysis failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Dead-zone analysis failed.")


async def _load_backtest_frames(days: int, db: AsyncSession) -> dict:
    """Load 1M candles from DB plus 4H/F&G from external APIs."""
    import httpx
    import pandas as pd
    from datetime import timedelta
    from sqlalchemy import select
    from indicators.binance_ws import REST_BASE_COM, REST_BASE_US, SYMBOL_UPPER

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

    df_4h: Optional[pd.DataFrame] = None
    try:
        limit_4h = min(1000, (days + 10) * 6 + 1)
        params_4h = {
            "symbol": SYMBOL_UPPER,
            "interval": "4h",
            "limit": limit_4h,
        }
        endpoints = (
            [REST_BASE_US, REST_BASE_COM]
            if settings.BINANCE_USE_US_ENDPOINT
            else [REST_BASE_COM, REST_BASE_US]
        )
        for base in endpoints:
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get(
                        f"{base}/api/v3/klines", params=params_4h
                    )
                    resp.raise_for_status()
                    klines_4h = resp.json()
                rows_4h = [
                    {
                        "timestamp": pd.Timestamp(k[0], unit="ms", tz="UTC"),
                        "open": float(k[1]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                        "close": float(k[4]),
                        "volume": float(k[7]),
                    }
                    for k in klines_4h[:-1]
                ]
                df_4h = pd.DataFrame(rows_4h).set_index("timestamp")
                break
            except Exception as exc:
                logger.warning("Backtest 4H fetch failed from %s: %s", base, exc)
    except Exception as exc:
        logger.warning("Could not fetch 4H candles for backtest: %s", exc)

    fg_history: Optional[list] = None
    try:
        async with NewsFetcher() as fetcher:
            fg_history = await fetcher.fetch_fear_greed_historical(days=days + 2)
    except Exception as exc:
        logger.warning("Could not fetch historical F&G for backtest: %s", exc)

    return {"df": df, "df_4h": df_4h, "fg_history": fg_history}


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


def _trend_label(trend: int) -> str:
    """Human-readable 4H trend for WAIT broadcasts."""
    if trend == +1:
        return "BULLISH"
    if trend == -1:
        return "BEARISH"
    return "NEUTRAL"


def _build_gate_block_reason(
    signal_type: str,
    *,
    signal_is_bullish: bool,
    signal_is_bearish: bool,
    trend: int,
    fg_value: Optional[int],
    trend_confirms: bool,
    fg_allows: bool,
) -> str:
    """Explain why a 1M signal was blocked (visibility only — gates unchanged)."""
    parts: list[str] = []
    if not trend_confirms:
        parts.append(f"1M={signal_type} but 4H={_trend_label(trend)}")
    if not fg_allows and fg_value is not None:
        if signal_is_bullish:
            parts.append(f"1M={signal_type} but F&G={fg_value} too high for BUY")
        elif signal_is_bearish:
            parts.append(f"1M={signal_type} but F&G={fg_value} too low for SELL")
    return "; ".join(parts) if parts else "Gate blocked"


async def _on_4h_candle_closed(candle: Candle, snapshot: IndicatorSnapshot) -> None:
    """Trend timeframe updated live — no waiting for REST poll."""
    global _4h_last_refreshed
    _4h_last_refreshed = datetime.now(timezone.utc)
    trend = _get_4h_trend_direction()
    logger.info(
        "4H trend live update: close=%.2f direction=%+d",
        candle.close,
        trend,
    )


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
        else:
            block_reason = _build_gate_block_reason(
                signal.signal_type.value,
                signal_is_bullish=signal_is_bullish,
                signal_is_bearish=signal_is_bearish,
                trend=trend,
                fg_value=fg_value,
                trend_confirms=trend_confirms,
                fg_allows=fg_allows,
            )
            wait_dict = {
                **signal.to_dict(),
                "type": "signal_wait",
                "display_state": "WAIT",
                "trend_4h": trend,
                "fear_greed": fg_value,
                "block_reason": block_reason,
            }
            await alert_manager.ws_broadcaster.broadcast(wait_dict)
            logger.info(
                "1M signal %s WAIT (not persisted): %s",
                signal.signal_type.value,
                block_reason,
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


async def _refresh_fear_greed() -> bool:
    """Fetch Fear & Greed index and update in-memory cache + WebSocket clients.

    Returns True when cache was updated successfully.
    """
    global _latest_fear_greed
    try:
        async with NewsFetcher() as fetcher:
            fg = await fetcher.fetch_fear_greed()
        if fg is None:
            logger.warning("F&G refresh skipped: API returned no data after retries")
            return False
        now = datetime.now(timezone.utc)
        _latest_fear_greed = {
            "value": fg.value,
            "classification": fg.classification,
            "timestamp": fg.timestamp.isoformat(),
            "updated_at": now.isoformat(),
        }
        logger.info("F&G refreshed: value=%d at %s", fg.value, now.isoformat())
        await alert_manager.ws_broadcaster.broadcast(
            {"type": "fear_greed", **_latest_fear_greed}
        )
        return True
    except Exception as exc:
        logger.error("Fear & Greed refresh failed: %s", exc, exc_info=True)
        return False


def _fear_greed_poll_alive() -> bool:
    """True when the F&G cache was refreshed within the last 70 minutes."""
    if _latest_fear_greed is None:
        return False
    updated_at = _latest_fear_greed.get("updated_at")
    if not updated_at:
        return False
    try:
        updated = datetime.fromisoformat(updated_at)
        age_s = (datetime.now(timezone.utc) - updated).total_seconds()
        return 0 <= age_s < FEAR_GREED_STALE_SECONDS
    except Exception:
        return False


async def _refresh_4h_candles() -> bool:
    """Re-fetch the latest 200 × 4H candles from Binance REST and reload
    the 4H indicator calculator so the trend gate always uses fresh data.

    The calculator is reset first to avoid pushing duplicates on top of the
    existing buffer, which would distort EMA/RSI calculations.

    Returns True on success.
    """
    global _4h_last_refreshed
    try:
        calculator_4h.reset()
        loaded = await binance_ws.preload_4h_candles(limit=200)
        if loaded > 0:
            snap = calculator_4h.get_snapshot()
            latest_close = snap.close_price if snap else None
            latest_ts = snap.timestamp if snap else None
            logger.info(
                "4H candles refreshed: latest close=%.2f at %s",
                latest_close or 0.0,
                latest_ts,
            )
            _4h_last_refreshed = datetime.now(timezone.utc)
            return True
        logger.warning("4H candle refresh returned 0 candles — keeping stale data")
        return False
    except Exception as exc:
        logger.error("4H candle refresh failed: %s", exc, exc_info=True)
        return False


async def _4h_refresh_loop() -> None:
    """Background loop: REST resync of 4H candles every 5 minutes.

    Primary updates arrive via the kline_4h WebSocket stream on each close.
    This loop catches drift after reconnects or missed events.
    """
    logger.info("4H refresh loop started (interval=%ds)", _4H_REFRESH_INTERVAL_S)
    while True:
        try:
            await asyncio.sleep(_4H_REFRESH_INTERVAL_S)
            await _refresh_4h_candles()
        except asyncio.CancelledError:
            logger.info("4H refresh loop cancelled")
            break
        except Exception as exc:
            logger.error("4H refresh loop error: %s", exc, exc_info=True)
            await asyncio.sleep(60)


async def _fear_greed_poll_loop() -> None:
    """Background loop: refresh Fear & Greed every hour.

    Matches _news_poll_loop structure: fetch first, then sleep (not sleep-first).
    """
    logger.info("F&G poll loop started (interval=%ds)", FEAR_GREED_POLL_INTERVAL_S)
    while True:
        try:
            logger.info(
                "F&G poll tick, next sleep in %ds after refresh",
                FEAR_GREED_POLL_INTERVAL_S,
            )
            await _refresh_fear_greed()
            logger.info(
                "F&G poll tick complete, sleeping %ds until next iteration",
                FEAR_GREED_POLL_INTERVAL_S,
            )
            await asyncio.sleep(FEAR_GREED_POLL_INTERVAL_S)
        except asyncio.CancelledError:
            logger.info("F&G poll loop cancelled")
            break
        except Exception as exc:
            logger.error("Fear & Greed poll loop error: %s", exc, exc_info=True)
            await asyncio.sleep(60)


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

        global _last_news_fetch, _news_count
        _last_news_fetch = datetime.now(timezone.utc)
        _news_count = len(articles)

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
    global _last_signal_at
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
            _last_signal_at = signal.generated_at
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
        "atr_14": snap.atr_14,
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
