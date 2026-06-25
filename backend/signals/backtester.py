"""
Backtesting engine for BTC Signal Pro — Phase 6.

Replays historical OHLCV data through the IndicatorCalculator and
SignalEngine to measure real performance of the signal logic.

Two run modes are supported when called from /api/backtest:

  1. 1M-only   — raw signal engine output with no gating (original behaviour).
  2. Full pipeline — 1M signals filtered through the same 4H trend gate and
                     Fear & Greed macro filter that govern live trades.

Metrics computed (for each mode):
  - Total signals fired
  - Win rate (%)
  - Average profit per winning trade (%)
  - Average loss per losing trade (%)
  - Maximum drawdown (%)
  - Profit factor (gross profit / gross loss)
  - Sharpe-ratio proxy (mean return / std return)

A "trade" is simulated as:
  - Entry at signal close price
  - Exit when either take-profit or stop-loss is hit (using subsequent OHLC)
  - If neither is hit within max_bars candles → exit at close of last bar
"""

import bisect
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

from indicators.calculator import Candle, IndicatorCalculator
from signals.engine import SignalEngine, SignalResult, SignalType

logger = logging.getLogger(__name__)

# Max candles to hold a trade before force-exiting
DEFAULT_MAX_HOLD_BARS = 60  # 60 minutes


@dataclass
class Trade:
    """A single simulated trade."""

    signal_type: SignalType
    confidence: float
    entry_price: float
    take_profit: Optional[float]
    stop_loss: Optional[float]
    entry_time: datetime
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    exit_reason: str = ""  # TP_HIT | SL_HIT | TIMEOUT
    pnl_pct: Optional[float] = None
    is_winner: Optional[bool] = None


@dataclass
class BacktestResult:
    """Aggregated performance statistics from a backtest run.

    The ``_1m`` fields reflect the raw signal engine with no gating
    (same as the original backtester).  The ``gated_*`` fields reflect
    the full live pipeline (1M + 4H trend + Fear & Greed filter) and are
    only populated when ``has_gated_run`` is True.
    """

    # ── 1M-only (raw, no gating) ──────────────────────────────────────────
    total_signals: int = 0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate_pct: float = 0.0
    avg_profit_pct: float = 0.0
    avg_loss_pct: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_proxy: float = 0.0
    total_return_pct: float = 0.0
    trades: list[Trade] = field(default_factory=list)

    # ── Full pipeline (1M + 4H trend gate + F&G filter) ───────────────────
    has_gated_run: bool = False
    gated_total_signals: int = 0
    gated_total_trades: int = 0
    gated_winning_trades: int = 0
    gated_losing_trades: int = 0
    gated_win_rate_pct: float = 0.0
    gated_avg_profit_pct: float = 0.0
    gated_avg_loss_pct: float = 0.0
    gated_profit_factor: float = 0.0
    gated_max_drawdown_pct: float = 0.0
    gated_sharpe_proxy: float = 0.0
    gated_total_return_pct: float = 0.0
    signals_blocked_by_4h_trend: int = 0
    signals_blocked_by_fg: int = 0

    def to_dict(self) -> dict:
        d: dict = {
            "total_signals": self.total_signals,
            "total_trades": self.total_trades,
            "win_rate_pct": round(self.win_rate_pct, 2),
            "avg_profit_pct": round(self.avg_profit_pct, 4),
            "avg_loss_pct": round(self.avg_loss_pct, 4),
            "profit_factor": round(self.profit_factor, 4),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "sharpe_proxy": round(self.sharpe_proxy, 4),
            "total_return_pct": round(self.total_return_pct, 4),
        }
        if self.has_gated_run:
            d["gated"] = {
                "total_signals": self.gated_total_signals,
                "total_trades": self.gated_total_trades,
                "winning_trades": self.gated_winning_trades,
                "losing_trades": self.gated_losing_trades,
                "win_rate_pct": round(self.gated_win_rate_pct, 2),
                "avg_profit_pct": round(self.gated_avg_profit_pct, 4),
                "avg_loss_pct": round(self.gated_avg_loss_pct, 4),
                "profit_factor": round(self.gated_profit_factor, 4),
                "max_drawdown_pct": round(self.gated_max_drawdown_pct, 4),
                "sharpe_proxy": round(self.gated_sharpe_proxy, 4),
                "total_return_pct": round(self.gated_total_return_pct, 4),
                "signals_blocked_by_4h_trend": self.signals_blocked_by_4h_trend,
                "signals_blocked_by_fg": self.signals_blocked_by_fg,
            }
        return d


class BacktestEngine:
    """
    Runs the signal engine over a historical DataFrame and produces
    detailed performance metrics.

    df must have columns: [open, high, low, close, volume]
    with a DatetimeIndex.

    Optional gating parameters mirror the live pipeline:
      df_4h       — 4H OHLCV DataFrame for the same period (plus warmup).
                    When supplied the 4H trend gate is applied identically
                    to ``_get_4h_trend_direction()`` in main.py.
      fg_history  — List of daily F&G dicts returned by
                    NewsFetcher.fetch_fear_greed_historical().
                    When supplied the Fear & Greed macro filter is applied.
    """

    def __init__(self, max_hold_bars: int = DEFAULT_MAX_HOLD_BARS) -> None:
        self._max_hold_bars = max_hold_bars

    def run(
        self,
        df: pd.DataFrame,
        df_4h: Optional[pd.DataFrame] = None,
        fg_history: Optional[list] = None,
    ) -> BacktestResult:
        """
        Execute a full backtest on the provided OHLCV DataFrame.

        Processes candles sequentially to preserve look-ahead bias
        prevention: indicators are computed only from data available
        at that point in time.

        When df_4h and/or fg_history are provided a second gated pass is
        run after the 1M-only pass, applying the 4H trend gate and the
        Fear & Greed filter exactly as the live pipeline does.
        """
        if df.empty:
            logger.warning("Backtest called with empty DataFrame.")
            return BacktestResult()

        df = self._validate_dataframe(df)
        calculator = IndicatorCalculator()
        engine = SignalEngine()

        signals_fired: list[tuple[int, SignalResult]] = []  # (bar_index, signal)

        for i, (timestamp, row) in enumerate(df.iterrows()):
            candle = Candle(
                timestamp=timestamp,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
            snapshot = calculator.push_candle(candle)
            signal = engine.evaluate(snapshot)
            if signal and signal.signal_type != SignalType.HOLD:
                signals_fired.append((i, signal))
                logger.debug(
                    "Backtest signal at bar %d: %s conf=%.1f%%",
                    i, signal.signal_type.value, signal.confidence
                )

        trades = self._simulate_trades(df, signals_fired)
        result = self._compute_metrics(trades, len(signals_fired))

        # ── Gated pass: apply 4H trend + F&G filters ─────────────────────
        if df_4h is not None or fg_history is not None:
            trend_timeline, trend_ts = self._build_4h_trend_timeline(df_4h) if df_4h is not None else ({}, [])
            fg_lookup, fg_dates = self._build_fg_lookup(fg_history) if fg_history is not None else ({}, [])

            blocked_trend = 0
            blocked_fg = 0
            gated_signals: list[tuple[int, SignalResult]] = []

            for bar_idx, signal in signals_fired:
                signal_time = df.index[bar_idx]
                is_bullish = signal.signal_type.value in ("BUY", "STRONG_BUY")
                is_bearish = signal.signal_type.value in ("SELL", "STRONG_SELL")

                # 4H trend gate
                trend = self._lookup_4h_trend(trend_ts, trend_timeline, signal_time) if trend_ts else 0
                trend_confirms = (
                    (is_bullish and trend == +1)
                    or (is_bearish and trend == -1)
                    or trend == 0
                )
                if not trend_confirms:
                    blocked_trend += 1
                    logger.debug(
                        "Backtest: %s at %s blocked by 4H trend=%+d",
                        signal.signal_type.value, signal_time, trend,
                    )
                    continue

                # Fear & Greed macro filter
                fg_value = self._lookup_fg(fg_dates, fg_lookup, signal_time) if fg_dates else None
                fg_allows = True
                if fg_value is not None:
                    if is_bullish and fg_value >= 40:
                        fg_allows = False
                    elif is_bearish and fg_value <= 60:
                        fg_allows = False
                if not fg_allows:
                    blocked_fg += 1
                    logger.debug(
                        "Backtest: %s at %s blocked by F&G=%d",
                        signal.signal_type.value, signal_time, fg_value,
                    )
                    continue

                gated_signals.append((bar_idx, signal))

            gated_trades = self._simulate_trades(df, gated_signals)
            gated_metrics = self._compute_metrics(gated_trades, len(gated_signals))

            result.has_gated_run = True
            result.gated_total_signals = gated_metrics.total_signals
            result.gated_total_trades = gated_metrics.total_trades
            result.gated_winning_trades = gated_metrics.winning_trades
            result.gated_losing_trades = gated_metrics.losing_trades
            result.gated_win_rate_pct = gated_metrics.win_rate_pct
            result.gated_avg_profit_pct = gated_metrics.avg_profit_pct
            result.gated_avg_loss_pct = gated_metrics.avg_loss_pct
            result.gated_profit_factor = gated_metrics.profit_factor
            result.gated_max_drawdown_pct = gated_metrics.max_drawdown_pct
            result.gated_sharpe_proxy = gated_metrics.sharpe_proxy
            result.gated_total_return_pct = gated_metrics.total_return_pct
            result.signals_blocked_by_4h_trend = blocked_trend
            result.signals_blocked_by_fg = blocked_fg

            logger.info(
                "Gated backtest: %d/%d signals passed gates "
                "(%d blocked by 4H trend, %d blocked by F&G)",
                len(gated_signals), len(signals_fired), blocked_trend, blocked_fg,
            )

        return result

    # ── Private helpers ───────────────────────────────────────────────────

    def _validate_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ensure required columns exist and data is clean."""
        required = {"open", "high", "low", "close", "volume"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"DataFrame missing required columns: {missing}")
        return df.dropna(subset=list(required)).copy()

    def _simulate_trades(
        self, df: pd.DataFrame, signals: list[tuple[int, SignalResult]]
    ) -> list[Trade]:
        """
        Simulate trade execution for each signal.

        For each signal, scans forward candles to find when TP or SL is hit.
        Uses high/low prices to detect intrabar touches (realistic fill model).
        """
        rows = df.reset_index()
        trades: list[Trade] = []

        for bar_idx, signal in signals:
            if bar_idx >= len(rows) - 1:
                continue  # No forward bars to simulate exit

            entry_row = rows.iloc[bar_idx]
            trade = Trade(
                signal_type=signal.signal_type,
                confidence=signal.confidence,
                entry_price=signal.entry_price,
                take_profit=signal.take_profit,
                stop_loss=signal.stop_loss,
                entry_time=entry_row.get("timestamp", entry_row.name),
            )

            is_long = signal.signal_type in (SignalType.STRONG_BUY, SignalType.BUY)

            # Scan forward bars
            end_idx = min(bar_idx + 1 + self._max_hold_bars, len(rows))
            exited = False

            for fwd_idx in range(bar_idx + 1, end_idx):
                fwd_row = rows.iloc[fwd_idx]
                high, low = float(fwd_row["high"]), float(fwd_row["low"])

                if is_long:
                    # Check stop-loss first (worst case)
                    if signal.stop_loss and low <= signal.stop_loss:
                        trade.exit_price = signal.stop_loss
                        trade.exit_reason = "SL_HIT"
                        trade.exit_time = fwd_row.get("timestamp", fwd_row.name)
                        exited = True
                        break
                    if signal.take_profit and high >= signal.take_profit:
                        trade.exit_price = signal.take_profit
                        trade.exit_reason = "TP_HIT"
                        trade.exit_time = fwd_row.get("timestamp", fwd_row.name)
                        exited = True
                        break
                else:
                    # Short trade
                    if signal.stop_loss and high >= signal.stop_loss:
                        trade.exit_price = signal.stop_loss
                        trade.exit_reason = "SL_HIT"
                        trade.exit_time = fwd_row.get("timestamp", fwd_row.name)
                        exited = True
                        break
                    if signal.take_profit and low <= signal.take_profit:
                        trade.exit_price = signal.take_profit
                        trade.exit_reason = "TP_HIT"
                        trade.exit_time = fwd_row.get("timestamp", fwd_row.name)
                        exited = True
                        break

            if not exited:
                last_row = rows.iloc[end_idx - 1]
                trade.exit_price = float(last_row["close"])
                trade.exit_reason = "TIMEOUT"
                trade.exit_time = last_row.get("timestamp", last_row.name)

            # Calculate PnL
            if trade.exit_price:
                if is_long:
                    trade.pnl_pct = (trade.exit_price - trade.entry_price) / trade.entry_price * 100
                else:
                    trade.pnl_pct = (trade.entry_price - trade.exit_price) / trade.entry_price * 100
                trade.is_winner = trade.pnl_pct > 0

            trades.append(trade)

        return trades

    def _compute_metrics(self, trades: list[Trade], total_signals: int) -> BacktestResult:
        """Aggregate trade results into performance statistics."""
        result = BacktestResult(total_signals=total_signals, trades=trades)

        completed = [t for t in trades if t.pnl_pct is not None]
        result.total_trades = len(completed)

        if not completed:
            return result

        pnls = [t.pnl_pct for t in completed]
        winners = [p for p in pnls if p > 0]
        losers = [p for p in pnls if p <= 0]

        result.winning_trades = len(winners)
        result.losing_trades = len(losers)
        result.win_rate_pct = len(winners) / len(pnls) * 100 if pnls else 0.0
        result.avg_profit_pct = float(np.mean(winners)) if winners else 0.0
        result.avg_loss_pct = float(np.mean(losers)) if losers else 0.0

        gross_profit = sum(p for p in pnls if p > 0)
        gross_loss = abs(sum(p for p in pnls if p < 0))
        result.profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        result.total_return_pct = float(np.sum(pnls))

        # Max drawdown (equity curve based)
        equity = np.cumsum(pnls)
        running_max = np.maximum.accumulate(equity)
        drawdowns = running_max - equity
        result.max_drawdown_pct = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

        # Sharpe-ratio proxy (no risk-free rate, annualisation omitted)
        std = float(np.std(pnls))
        result.sharpe_proxy = float(np.mean(pnls)) / std if std > 0 else 0.0

        return result

    # ── 4H trend gate helpers ─────────────────────────────────────────────

    def _build_4h_trend_timeline(
        self, df_4h: pd.DataFrame
    ) -> tuple[dict, list]:
        """Replay 4H candles through a fresh IndicatorCalculator and record
        the trend direction at each closed candle.

        Returns ``(trend_map, sorted_timestamps)`` where
        ``trend_map[ts] = +1 | 0 | -1`` and ``sorted_timestamps`` is the
        sorted list of 4H close times for binary-search lookups.
        """
        calc = IndicatorCalculator()
        trend_map: dict = {}

        for timestamp, row in df_4h.iterrows():
            candle = Candle(
                timestamp=timestamp,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
            snap = calc.push_candle(candle)
            trend = 0
            if snap.close_price is not None and snap.ema_20 is not None and snap.ema_50 is not None:
                p, e20, e50, rsi = snap.close_price, snap.ema_20, snap.ema_50, snap.rsi_14
                if p > e20 > e50 and (rsi is None or rsi < 70):
                    trend = +1
                elif p < e20 < e50 and (rsi is None or rsi > 30):
                    trend = -1
            trend_map[timestamp] = trend

        sorted_ts = sorted(trend_map.keys())
        logger.info(
            "4H trend timeline built: %d candles, %d bullish, %d bearish",
            len(sorted_ts),
            sum(1 for v in trend_map.values() if v == +1),
            sum(1 for v in trend_map.values() if v == -1),
        )
        return trend_map, sorted_ts

    def _lookup_4h_trend(
        self,
        sorted_ts: list,
        trend_map: dict,
        signal_time,
    ) -> int:
        """Return the most recent 4H trend direction at or before signal_time."""
        idx = bisect.bisect_right(sorted_ts, signal_time) - 1
        if idx < 0:
            return 0
        return trend_map[sorted_ts[idx]]

    # ── Fear & Greed gate helpers ─────────────────────────────────────────

    def _build_fg_lookup(
        self, fg_history: list[dict]
    ) -> tuple[dict, list]:
        """Build a date-keyed F&G lookup from the historical list.

        Returns ``(fg_map, sorted_dates)`` where ``fg_map[date] = int_value``
        and ``sorted_dates`` is sorted for binary-search lookups.
        """
        fg_map: dict = {}
        for entry in fg_history:
            ts = entry.get("timestamp")
            if ts is None:
                continue
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            date = ts.date() if hasattr(ts, "date") else ts
            fg_map[date] = int(entry["value"])

        sorted_dates = sorted(fg_map.keys())
        return fg_map, sorted_dates

    def _lookup_fg(
        self,
        sorted_dates: list,
        fg_map: dict,
        signal_time,
    ) -> Optional[int]:
        """Return the F&G value for the day of signal_time (or nearest prior day)."""
        if not sorted_dates:
            return None

        if hasattr(signal_time, "date"):
            signal_date = signal_time.date()
        elif hasattr(signal_time, "to_pydatetime"):
            signal_date = signal_time.to_pydatetime().date()
        else:
            return None

        # Exact match
        if signal_date in fg_map:
            return fg_map[signal_date]

        # Nearest prior date
        idx = bisect.bisect_right(sorted_dates, signal_date) - 1
        if idx >= 0:
            return fg_map[sorted_dates[idx]]

        return None
