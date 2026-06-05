"""
Technical indicator calculator for BTC Signal Pro.

Uses the `ta` library (which wraps pandas) so every indicator is
computed on a rolling window of OHLCV candles.  The IndicatorCalculator
maintains an internal circular buffer of the last MAX_CANDLES candles;
call push_candle() as new price data arrives, then get_snapshot() to
read the latest computed values.

All values may be None during the warm-up period (not enough history).
"""

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Optional

import numpy as np
import pandas as pd
import ta

logger = logging.getLogger(__name__)

# Keep enough history for EMA-200 warm-up plus some headroom
MAX_CANDLES = 300


@dataclass
class Candle:
    """Minimal OHLCV representation for indicator computation."""

    timestamp: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class IndicatorSnapshot:
    """
    All computed indicator values at a specific moment in time.

    Fields set to None mean there is insufficient history to compute
    the indicator yet (warm-up period).
    """

    timestamp: Optional[pd.Timestamp] = None

    # RSI
    rsi_14: Optional[float] = None

    # MACD
    macd_line: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_histogram: Optional[float] = None

    # EMA
    ema_20: Optional[float] = None
    ema_50: Optional[float] = None
    ema_200: Optional[float] = None

    # Bollinger Bands
    bb_upper: Optional[float] = None
    bb_middle: Optional[float] = None
    bb_lower: Optional[float] = None
    bb_percent_b: Optional[float] = None  # position within bands (0=lower, 1=upper)

    # Volume
    volume_sma_20: Optional[float] = None
    volume_ratio: Optional[float] = None  # current volume / 20-period SMA

    # Latest close price (always available after first candle)
    close_price: Optional[float] = None


class IndicatorCalculator:
    """
    Maintains a rolling window of OHLCV candles and computes all
    technical indicators on each update.

    Thread-safe for single-producer, single-consumer usage (the
    Binance WebSocket feeds one candle at a time into push_candle).
    """

    def __init__(self, max_candles: int = MAX_CANDLES) -> None:
        self._max_candles = max_candles
        self._buffer: Deque[Candle] = deque(maxlen=max_candles)
        self._last_snapshot: Optional[IndicatorSnapshot] = None

    # ── Public API ────────────────────────────────────────────────────────

    def push_candle(self, candle: Candle) -> IndicatorSnapshot:
        """
        Add a new candle to the rolling window and recompute all indicators.

        Returns the latest IndicatorSnapshot.  Any computation error is
        caught so the application continues running with the previous
        snapshot; the error is logged for debugging.
        """
        self._buffer.append(candle)
        try:
            self._last_snapshot = self._compute()
        except Exception as exc:
            logger.error("Indicator computation failed: %s", exc, exc_info=True)
            if self._last_snapshot is None:
                self._last_snapshot = IndicatorSnapshot(
                    timestamp=candle.timestamp, close_price=candle.close
                )
        return self._last_snapshot

    def get_snapshot(self) -> Optional[IndicatorSnapshot]:
        """Return the most recently computed snapshot, or None if no data yet."""
        return self._last_snapshot

    def candle_count(self) -> int:
        """Number of candles currently in the rolling window."""
        return len(self._buffer)

    # ── Private helpers ───────────────────────────────────────────────────

    def _to_dataframe(self) -> pd.DataFrame:
        """Convert the internal deque to a pandas DataFrame."""
        rows = [
            {
                "timestamp": c.timestamp,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in self._buffer
        ]
        df = pd.DataFrame(rows)
        df.set_index("timestamp", inplace=True)
        # Ensure numeric dtypes; coerce bad values to NaN
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    def _safe_float(self, series: pd.Series) -> Optional[float]:
        """Extract the last value from a pandas Series, return None if NaN/empty."""
        if series is None or series.empty:
            return None
        val = series.iloc[-1]
        return None if (val is None or (isinstance(val, float) and np.isnan(val))) else float(val)

    def _compute(self) -> IndicatorSnapshot:
        """
        Recompute all indicators from the current rolling window.

        Uses the `ta` library which provides vectorised pandas implementations
        of every indicator.  Each block is wrapped in its own try/except so
        a failure in one indicator does not block the others.
        """
        df = self._to_dataframe()
        snap = IndicatorSnapshot(
            timestamp=df.index[-1],
            close_price=float(df["close"].iloc[-1]),
        )

        # ── RSI (14-period) ───────────────────────────────────────────────
        try:
            rsi = ta.momentum.RSIIndicator(close=df["close"], window=14)
            snap.rsi_14 = self._safe_float(rsi.rsi())
        except Exception as exc:
            logger.warning("RSI computation error: %s", exc)

        # ── MACD (12, 26, 9) ──────────────────────────────────────────────
        try:
            macd = ta.trend.MACD(
                close=df["close"], window_slow=26, window_fast=12, window_sign=9
            )
            snap.macd_line = self._safe_float(macd.macd())
            snap.macd_signal = self._safe_float(macd.macd_signal())
            snap.macd_histogram = self._safe_float(macd.macd_diff())
        except Exception as exc:
            logger.warning("MACD computation error: %s", exc)

        # ── EMA 20 / 50 / 200 ─────────────────────────────────────────────
        for period, attr in ((20, "ema_20"), (50, "ema_50"), (200, "ema_200")):
            try:
                ema = ta.trend.EMAIndicator(close=df["close"], window=period)
                setattr(snap, attr, self._safe_float(ema.ema_indicator()))
            except Exception as exc:
                logger.warning("EMA-%d computation error: %s", period, exc)

        # ── Bollinger Bands (20-period, 2 std-dev) ─────────────────────────
        try:
            bb = ta.volatility.BollingerBands(
                close=df["close"], window=20, window_dev=2
            )
            snap.bb_upper = self._safe_float(bb.bollinger_hband())
            snap.bb_middle = self._safe_float(bb.bollinger_mavg())
            snap.bb_lower = self._safe_float(bb.bollinger_lband())
            snap.bb_percent_b = self._safe_float(bb.bollinger_pband())
        except Exception as exc:
            logger.warning("Bollinger Bands computation error: %s", exc)

        # ── Volume SMA-20 and ratio ────────────────────────────────────────
        try:
            vol_sma = df["volume"].rolling(window=20).mean()
            snap.volume_sma_20 = self._safe_float(vol_sma)
            if snap.volume_sma_20 and snap.volume_sma_20 > 0:
                snap.volume_ratio = float(df["volume"].iloc[-1]) / snap.volume_sma_20
        except Exception as exc:
            logger.warning("Volume analysis computation error: %s", exc)

        return snap
