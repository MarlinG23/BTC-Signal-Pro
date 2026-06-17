"""
Binance WebSocket client for live BTC/USDT price data.

Subscribes to:
  - kline_1m stream  → 1-minute OHLCV candles
  - bookTicker stream → real-time best bid/ask
  - aggTrade stream   → individual trade events (for volume analysis)

Reconnects automatically with exponential back-off on any failure.
The caller registers a callback via on_candle_closed() which fires
every time a 1-minute candle is completed.
"""

import asyncio
import json
import logging
import time
from typing import Callable, Awaitable, Optional

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from indicators.calculator import Candle, IndicatorCalculator, IndicatorSnapshot
from config import settings

logger = logging.getLogger(__name__)

# Binance stream URLs
# binance.us is the US-regulated endpoint — not geo-blocked on US cloud servers
# (binance.com returns HTTP 451 from Railway US West due to legal restrictions)
WS_BASE = "wss://stream.binance.us:9443/stream"
WS_BASE_COM = "wss://stream.binance.com:9443/stream"
WS_BASE_TESTNET = "wss://testnet.binance.vision/stream"

# REST endpoints for historical candle preload
REST_BASE_US = "https://api.binance.us"
REST_BASE_COM = "https://api.binance.com"

SYMBOL = "btcusdt"
SYMBOL_UPPER = "BTCUSDT"

# Back-off config
INITIAL_BACKOFF_S = 1
MAX_BACKOFF_S = 60


class BinanceWebSocketClient:
    """
    Manages a persistent connection to the Binance combined WebSocket stream.

    Usage::

        client = BinanceWebSocketClient(calculator)
        client.on_candle_closed(my_async_callback)
        await client.run()  # runs forever, reconnecting as needed
    """

    def __init__(
        self,
        calculator: IndicatorCalculator,
        calculator_4h: Optional[IndicatorCalculator] = None,
    ) -> None:
        self._calculator = calculator
        self._calculator_4h = calculator_4h
        self._candle_callbacks: list[Callable[[Candle, IndicatorSnapshot], Awaitable[None]]] = []
        self._tick_callbacks: list[Callable[[dict], Awaitable[None]]] = []
        self._running = False
        self._latest_price: Optional[float] = None
        self._latest_price_time: Optional[float] = None
        self._connected = False
        self._last_message_time: Optional[float] = None

    # ── Public API ────────────────────────────────────────────────────────

    def on_candle_closed(
        self, callback: Callable[[Candle, IndicatorSnapshot], Awaitable[None]]
    ) -> None:
        """Register an async callback fired when a 1-minute candle closes."""
        self._candle_callbacks.append(callback)

    def on_price_tick(self, callback: Callable[[dict], Awaitable[None]]) -> None:
        """Register an async callback fired on every bookTicker update."""
        self._tick_callbacks.append(callback)

    @property
    def latest_price(self) -> Optional[float]:
        return self._latest_price

    @property
    def ws_connected(self) -> bool:
        return self._connected

    @property
    def ws_last_message_seconds(self) -> Optional[float]:
        if self._last_message_time is None:
            return None
        return round(time.time() - self._last_message_time, 1)

    def update_latest_price(self, price: float) -> None:
        """Update the cached price (used by REST fallback when Binance is unavailable)."""
        self._latest_price = price
        self._latest_price_time = time.time()

    async def preload_historical_candles(self, limit: int = 50) -> int:
        """Fetch the last `limit` closed 1-minute candles from Binance REST API
        and push them into the calculator so indicators are ready before the
        WebSocket delivers the first live candle.

        Tries binance.us first (not geo-blocked on Railway US West), then
        falls back to binance.com.  Returns the number of candles loaded.
        """
        import httpx

        endpoints = (
            [REST_BASE_US, REST_BASE_COM]
            if settings.BINANCE_USE_US_ENDPOINT
            else [REST_BASE_COM, REST_BASE_US]
        )
        params = {
            "symbol": SYMBOL_UPPER,
            "interval": "1m",
            "limit": limit,
        }

        for base in endpoints:
            url = f"{base}/api/v3/klines"
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(url, params=params)
                    resp.raise_for_status()
                    klines = resp.json()

                count = 0
                for k in klines[:-1]:  # skip the current unclosed candle
                    candle = Candle(
                        timestamp=pd.Timestamp(k[0], unit="ms", tz="UTC"),
                        open=float(k[1]),
                        high=float(k[2]),
                        low=float(k[3]),
                        close=float(k[4]),
                        # k[7] = quote asset volume (USDT dollar volume)
                        # k[5] = base asset volume (raw BTC — too small on Binance US)
                        volume=float(k[7]),
                    )
                    self._calculator.push_candle(candle)
                    # Update latest price from historical data
                    self._latest_price = float(k[4])
                    count += 1

                logger.info(
                    "Preloaded %d historical candles from %s — indicators ready",
                    count, base,
                )
                return count

            except Exception as exc:
                logger.warning("Historical preload failed from %s: %s", base, exc)

        logger.warning("Could not preload historical candles from any endpoint")
        return 0

    async def preload_4h_candles(self, limit: int = 200) -> int:
        """Fetch the last `limit` closed 4-hour candles and push them into the
        4H IndicatorCalculator so the trend signal is available immediately.

        With 200 candles the EMA-200 on the 4H chart is fully warmed up,
        giving a reliable long-term trend direction.
        """
        if self._calculator_4h is None:
            return 0

        import httpx

        endpoints = (
            [REST_BASE_US, REST_BASE_COM]
            if settings.BINANCE_USE_US_ENDPOINT
            else [REST_BASE_COM, REST_BASE_US]
        )
        params = {
            "symbol": SYMBOL_UPPER,
            "interval": "4h",
            "limit": limit,
        }

        for base in endpoints:
            url = f"{base}/api/v3/klines"
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get(url, params=params)
                    resp.raise_for_status()
                    klines = resp.json()

                count = 0
                for k in klines[:-1]:  # skip the current (still open) 4H candle
                    candle = Candle(
                        timestamp=pd.Timestamp(k[0], unit="ms", tz="UTC"),
                        open=float(k[1]),
                        high=float(k[2]),
                        low=float(k[3]),
                        close=float(k[4]),
                        volume=float(k[7]),  # USDT quote volume
                    )
                    self._calculator_4h.push_candle(candle)
                    count += 1

                logger.info(
                    "Preloaded %d × 4H candles from %s — trend indicators ready",
                    count, base,
                )
                return count

            except Exception as exc:
                logger.warning("4H candle preload failed from %s: %s", base, exc)

        logger.warning("Could not preload 4H candles from any endpoint")
        return 0

    async def run(self, skip_preload: bool = False) -> None:
        """
        Start the WebSocket connection loop.  Reconnects indefinitely with
        exponential back-off.  Call stop() to terminate gracefully.
        """
        self._running = True
        backoff = INITIAL_BACKOFF_S
        attempt = 0

        if not skip_preload:
            await self.preload_historical_candles(limit=50)
            await self.preload_4h_candles(limit=200)

        while self._running:
            attempt += 1
            try:
                await self._connect()
                backoff = INITIAL_BACKOFF_S  # reset on successful connection
            except asyncio.CancelledError:
                logger.info("BinanceWebSocketClient cancelled.")
                break
            except Exception as exc:
                logger.error(
                    "WebSocket error (attempt %d): %s — reconnecting in %ds",
                    attempt, exc, backoff
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_S)

    async def stop(self) -> None:
        """Signal the run loop to stop after the current connection closes."""
        self._running = False

    # ── Private helpers ───────────────────────────────────────────────────

    def _build_url(self) -> str:
        if settings.BINANCE_TESTNET:
            base = WS_BASE_TESTNET
        elif settings.BINANCE_USE_US_ENDPOINT:
            base = WS_BASE          # binance.us — not geo-blocked on US servers
        else:
            base = WS_BASE_COM      # binance.com — blocked on Railway US West
        streams = [
            f"{SYMBOL}@kline_1m",
            f"{SYMBOL}@bookTicker",
            f"{SYMBOL}@aggTrade",
        ]
        return f"{base}?streams={'/'.join(streams)}"

    async def _connect(self) -> None:
        url = self._build_url()
        logger.info("Connecting to Binance WebSocket: %s", url)

        async with websockets.connect(
            url,
            ping_interval=20,
            ping_timeout=10,
            close_timeout=5,
        ) as ws:
            self._connected = True
            logger.info("Binance WebSocket connected.")
            try:
                async for raw_message in ws:
                    if not self._running:
                        break
                    self._last_message_time = time.time()
                    try:
                        await self._dispatch(json.loads(raw_message))
                    except Exception as exc:
                        logger.warning("Error processing WebSocket message: %s", exc)
            finally:
                self._connected = False

    async def _dispatch(self, envelope: dict) -> None:
        """Route an incoming combined-stream envelope to the correct handler."""
        stream_name: str = envelope.get("stream", "")
        data: dict = envelope.get("data", {})

        if "@kline_1m" in stream_name:
            await self._handle_kline(data)
        elif "@bookTicker" in stream_name:
            await self._handle_book_ticker(data)
        elif "@aggTrade" in stream_name:
            await self._handle_agg_trade(data)

    async def _handle_kline(self, data: dict) -> None:
        """
        Process a kline (candlestick) event.

        Binance sends an update on every trade within the minute.
        We only push a Candle to the calculator when the candle is
        fully closed (k.x == True) so we don't double-count partial bars.
        """
        k = data.get("k", {})
        if not k.get("x"):  # candle not yet closed
            return

        try:
            candle = Candle(
                timestamp=pd.Timestamp(k["t"], unit="ms", tz="UTC"),
                open=float(k["o"]),
                high=float(k["h"]),
                low=float(k["l"]),
                close=float(k["c"]),
                # "q" = quote asset volume (USDT dollar volume)
                # "v" = base asset volume (raw BTC — too small on Binance US)
                volume=float(k["q"]),
            )
        except (KeyError, ValueError) as exc:
            logger.error("Malformed kline payload: %s — %s", k, exc)
            return

        snapshot = self._calculator.push_candle(candle)
        logger.debug(
            "Candle closed: close=%.2f rsi=%.1f",
            candle.close,
            snapshot.rsi_14 if snapshot.rsi_14 else 0,
        )

        for cb in self._candle_callbacks:
            try:
                await cb(candle, snapshot)
            except Exception as exc:
                logger.error("Candle callback error: %s", exc, exc_info=True)

    async def _handle_book_ticker(self, data: dict) -> None:
        """Update the latest best-bid/ask price from bookTicker events."""
        try:
            best_ask = float(data["a"])
            self._latest_price = best_ask
            self._latest_price_time = time.time()
        except (KeyError, ValueError):
            pass

        for cb in self._tick_callbacks:
            try:
                await cb(data)
            except Exception as exc:
                logger.error("Tick callback error: %s", exc, exc_info=True)

    async def _handle_agg_trade(self, data: dict) -> None:
        """
        Update latest price from aggregate trades.

        aggTrade arrives more frequently than bookTicker and provides
        the actual last-traded price rather than bid/ask.
        """
        try:
            self._latest_price = float(data["p"])
            self._latest_price_time = time.time()
        except (KeyError, ValueError):
            pass


# pandas is needed inside _handle_kline — import here to keep the
# module-level import section clean and avoid circular issues.
import pandas as pd  # noqa: E402
