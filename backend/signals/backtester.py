"""
Backtesting engine for BTC Signal Pro — Phase 6.

Replays historical OHLCV data through the IndicatorCalculator and
SignalEngine to measure real performance of the signal logic.

Metrics computed:
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

import logging
from dataclasses import dataclass, field
from datetime import datetime
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
    """Aggregated performance statistics from a backtest run."""

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

    def to_dict(self) -> dict:
        return {
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


class BacktestEngine:
    """
    Runs the signal engine over a historical DataFrame and produces
    detailed performance metrics.

    df must have columns: [open, high, low, close, volume]
    with a DatetimeIndex.
    """

    def __init__(self, max_hold_bars: int = DEFAULT_MAX_HOLD_BARS) -> None:
        self._max_hold_bars = max_hold_bars

    def run(self, df: pd.DataFrame) -> BacktestResult:
        """
        Execute a full backtest on the provided OHLCV DataFrame.

        Processes candles sequentially to preserve look-ahead bias
        prevention: indicators are computed only from data available
        at that point in time.
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
        return self._compute_metrics(trades, len(signals_fired))

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
                close = float(fwd_row["close"])

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
