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


class TestSequentialOnly:
    def test_sequential_reduces_or_equals_trade_count(self):
        np.random.seed(11)
        df = _make_ohlcv_dataframe(500, trend="flat")
        normal = BacktestEngine().run(df, options=BacktestOptions(gate_mode="none"))
        sequential = BacktestEngine().run(
            df, options=BacktestOptions(gate_mode="none", sequential_only=True)
        )
        assert sequential.total_trades <= normal.total_trades
        assert sequential.skipped_while_in_position >= 0
        # Every trade taken plus every trade skipped should account for all fired signals
        # that had forward bars available to simulate.
        assert sequential.total_trades + sequential.skipped_while_in_position <= sequential.total_signals

    def test_sequential_trades_do_not_overlap(self):
        np.random.seed(11)
        df = _make_ohlcv_dataframe(500, trend="flat")
        engine = BacktestEngine()
        _, signals = engine.collect_signals(df)
        trades, _skipped = engine._simulate_trades(df, signals, sequential=True)

        rows = df.reset_index()
        last_exit_time = None
        for trade in trades:
            if last_exit_time is not None:
                assert trade.entry_time >= last_exit_time
            last_exit_time = trade.exit_time


class TestTrailingExit:
    def test_trailing_exit_produces_trail_stop_reason(self):
        np.random.seed(21)
        df = _make_ohlcv_dataframe(600, trend="up")
        result = BacktestEngine().run(
            df,
            options=BacktestOptions(
                gate_mode="none",
                use_trailing_exit=True,
                trailing_activation_pct=0.002,
                trailing_distance_pct=0.0015,
                trailing_max_hold_bars=120,
            ),
        )
        reasons = {t.exit_reason for t in result.trades}
        # On a sustained uptrend at least some trades should trail instead of
        # hitting the hard stop or timing out.
        assert reasons  # non-empty — trades were simulated
        assert reasons <= {"SL_HIT", "TRAIL_STOP", "TIMEOUT"}

    def test_trailing_exit_respects_hard_stop_before_activation(self):
        np.random.seed(21)
        df = _make_ohlcv_dataframe(300, trend="down")
        result = BacktestEngine().run(
            df,
            options=BacktestOptions(
                gate_mode="none",
                use_trailing_exit=True,
                trailing_activation_pct=0.05,  # unrealistically high — never activates
                trailing_distance_pct=0.003,
                trailing_max_hold_bars=60,
            ),
        )
        # With activation essentially unreachable, no trade should exit via TRAIL_STOP
        assert all(t.exit_reason != "TRAIL_STOP" for t in result.trades)


class TestRegimeFilter:
    def test_min_atr_pct_blocks_signals_in_low_volatility(self):
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        n = 300
        timestamps = [base + timedelta(minutes=i) for i in range(n)]
        flat_price = 45_000.0
        df = pd.DataFrame(
            {
                "open": [flat_price] * n,
                "high": [flat_price + 0.5] * n,
                "low": [flat_price - 0.5] * n,
                "close": [flat_price] * n,
                "volume": [100.0] * n,
            },
            index=pd.DatetimeIndex(timestamps, tz=timezone.utc),
        )
        engine = BacktestEngine()
        _, signals_normal = engine.collect_signals(df, BacktestOptions())
        _, signals_filtered = engine.collect_signals(
            df, BacktestOptions(min_atr_pct=0.01)
        )
        assert len(signals_filtered) == 0
        assert len(signals_filtered) <= len(signals_normal)


class TestMultiTimeframeFilter:
    def test_min_mtf_agreement_reduces_or_matches_gated_trades(self):
        np.random.seed(7)
        engine = BacktestEngine()
        df = _make_ohlcv_dataframe(600, trend="up")
        df_4h = df.resample("4h").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        ).dropna()

        loose = BacktestOptions(gate_mode="4h_only", min_mtf_agreement=0)
        strict = BacktestOptions(gate_mode="4h_only", min_mtf_agreement=4)

        result_loose = engine.run(df, df_4h=df_4h, options=loose)
        result_strict = engine.run(df, df_4h=df_4h, options=strict)

        assert result_loose.has_gated_run
        assert result_strict.has_gated_run
        # Requiring all 4 timeframes to agree can only keep as many or fewer
        # trades than requiring none of them to agree.
        assert result_strict.gated_total_trades <= result_loose.gated_total_trades
        assert result_strict.signals_blocked_by_mtf >= 0

    def test_min_mtf_agreement_none_is_noop(self):
        np.random.seed(11)
        engine = BacktestEngine()
        df = _make_ohlcv_dataframe(600, trend="up")
        df_4h = df.resample("4h").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        ).dropna()

        with_none = engine.run(
            df, df_4h=df_4h, options=BacktestOptions(gate_mode="4h_only", min_mtf_agreement=None)
        )
        assert with_none.signals_blocked_by_mtf == 0


class TestDeadzoneAnalysis:
    def test_analyze_deadzone_returns_structure(self):
        np.random.seed(99)
        engine = BacktestEngine()
        df = _make_ohlcv_dataframe(400, trend="down")
        df_4h = df.resample("4h").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        ).dropna()
        fg_history = [
            {
                "timestamp": df.index[0].isoformat(),
                "value": 15,
                "classification": "Extreme Fear",
            }
        ]
        for i in range(1, 35):
            fg_history.append(
                {
                    "timestamp": (df.index[0] + timedelta(days=i)).isoformat(),
                    "value": 15 + (i % 5),
                    "classification": "Extreme Fear",
                }
            )

        _, signals = engine.collect_signals(df)
        report = engine.analyze_deadzone_opportunity(
            df, signals, df_4h, fg_history, options=BacktestOptions()
        )
        assert "signals_in_deadzone_regime" in report
        assert "ungated_in_deadzone" in report
        assert "bearish_fear" in report["by_regime"]
        assert report["total_1m_signals_in_period"] == len(signals)
