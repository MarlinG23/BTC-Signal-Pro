"""
Unit tests for the BacktestEngine.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

from signals.backtester import BacktestEngine, BacktestOptions, Trade, BacktestResult
from signals.engine import SignalType


def _make_ohlcv_dataframe(n: int = 300, start_price: float = 45_000.0, trend: str = "up") -> pd.DataFrame:
    """
    Generate a synthetic OHLCV DataFrame for backtesting.

    trend: "up" | "down" | "flat"
    """
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    timestamps = [base + timedelta(minutes=i) for i in range(n)]

    prices = []
    p = start_price
    for i in range(n):
        if trend == "up":
            p += np.random.normal(5, 20)
        elif trend == "down":
            p += np.random.normal(-5, 20)
        else:
            p += np.random.normal(0, 20)
        p = max(p, 100)  # floor
        prices.append(p)

    prices = np.array(prices)
    df = pd.DataFrame(
        {
            "open": prices - np.abs(np.random.normal(0, 10, n)),
            "high": prices + np.abs(np.random.normal(20, 10, n)),
            "low": prices - np.abs(np.random.normal(20, 10, n)),
            "close": prices,
            "volume": np.abs(np.random.normal(100, 30, n)),
        },
        index=pd.DatetimeIndex(timestamps, tz=timezone.utc),
    )
    # Ensure high >= close >= low
    df["high"] = np.maximum(df["high"], df["close"])
    df["low"] = np.minimum(df["low"], df["close"])
    return df


class TestBacktestEngineBasics:
    def test_empty_dataframe_returns_empty_result(self):
        engine = BacktestEngine()
        df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        result = engine.run(df)
        assert result.total_signals == 0
        assert result.total_trades == 0

    def test_missing_column_raises_value_error(self):
        engine = BacktestEngine()
        df = pd.DataFrame({"close": [45000], "volume": [100]})
        with pytest.raises(ValueError, match="missing required columns"):
            engine.run(df)

    def test_run_does_not_crash_on_uptrend(self):
        engine = BacktestEngine()
        df = _make_ohlcv_dataframe(300, trend="up")
        result = engine.run(df)
        assert isinstance(result, BacktestResult)

    def test_run_does_not_crash_on_downtrend(self):
        engine = BacktestEngine()
        df = _make_ohlcv_dataframe(300, trend="down")
        result = engine.run(df)
        assert isinstance(result, BacktestResult)


class TestBacktestMetrics:
    @pytest.fixture(scope="class")
    def result(self):
        """Run a backtest once for all tests in this class."""
        np.random.seed(42)
        engine = BacktestEngine()
        df = _make_ohlcv_dataframe(300, trend="up")
        return engine.run(df)

    def test_win_rate_in_valid_range(self, result):
        assert 0.0 <= result.win_rate_pct <= 100.0

    def test_total_trades_le_total_signals(self, result):
        # Some signals at the end of the dataset have no forward bars
        assert result.total_trades <= result.total_signals

    def test_to_dict_keys_present(self, result):
        d = result.to_dict()
        expected_keys = {
            "total_signals", "total_trades", "win_rate_pct",
            "avg_profit_pct", "avg_loss_pct", "profit_factor",
            "max_drawdown_pct", "sharpe_proxy", "total_return_pct",
        }
        assert expected_keys <= set(d.keys())

    def test_max_drawdown_non_negative(self, result):
        assert result.max_drawdown_pct >= 0

    def test_profit_factor_non_negative(self, result):
        # profit_factor == inf when there are no losing trades
        import math
        assert result.profit_factor >= 0 or math.isinf(result.profit_factor)


class TestBacktestTrades:
    def test_trade_exit_reason_valid(self):
        np.random.seed(7)
        engine = BacktestEngine()
        df = _make_ohlcv_dataframe(300, trend="up")
        result = engine.run(df)
        valid_reasons = {"TP_HIT", "SL_HIT", "TIMEOUT"}
        for trade in result.trades:
            assert trade.exit_reason in valid_reasons, (
                f"Unexpected exit reason: {trade.exit_reason}"
            )

    def test_pnl_sign_consistent_with_exit_reason_long(self):
        np.random.seed(7)
        engine = BacktestEngine()
        df = _make_ohlcv_dataframe(300, trend="up")
        result = engine.run(df)
        for trade in result.trades:
            if trade.pnl_pct is None:
                continue
            if trade.signal_type in (SignalType.BUY, SignalType.STRONG_BUY):
                if trade.exit_reason == "TP_HIT":
                    assert trade.pnl_pct > 0, "TP-hit long trade should be positive"
                elif trade.exit_reason == "SL_HIT":
                    assert trade.pnl_pct <= 0, "SL-hit long trade should be non-positive"

    def test_taker_fee_reduces_pnl(self):
        np.random.seed(7)
        df = _make_ohlcv_dataframe(300, trend="up")
        no_fee = BacktestEngine().run(df)
        with_fee = BacktestEngine().run(
            df,
            options=BacktestOptions(taker_fee_pct=0.04, gate_mode="none"),
        )
        if no_fee.total_trades > 0 and with_fee.total_trades > 0:
            assert with_fee.total_return_pct < no_fee.total_return_pct
            assert with_fee.total_return_pct_gross == pytest.approx(
                no_fee.total_return_pct, rel=1e-6
            )
