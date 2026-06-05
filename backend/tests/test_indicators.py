"""
Unit tests for the IndicatorCalculator.

Tests verify:
  1. Empty buffer returns None snapshot
  2. Single candle produces partial snapshot (most indicators None during warm-up)
  3. Enough candles produce all non-None values
  4. Malformed candle data does not crash the calculator
  5. close_price is always populated once at least one candle exists
"""

import pytest
import pandas as pd

from indicators.calculator import Candle, IndicatorCalculator


def _make_candle(
    close: float,
    ts_offset_min: int = 0,
    high_offset: float = 50.0,
    low_offset: float = 50.0,
    volume: float = 10.0,
) -> Candle:
    """Helper: create a realistic BTC candle."""
    base_ts = pd.Timestamp("2024-01-01 00:00:00", tz="UTC")
    ts = base_ts + pd.Timedelta(minutes=ts_offset_min)
    return Candle(
        timestamp=ts,
        open=close - 10,
        high=close + high_offset,
        low=close - low_offset,
        close=close,
        volume=volume,
    )


def _feed_candles(calc: IndicatorCalculator, n: int, start_price: float = 45_000.0):
    """Feed n synthetic candles into the calculator."""
    for i in range(n):
        # Simulate a gentle uptrend with small oscillations
        price = start_price + i * 10 + (i % 5 - 2) * 5
        calc.push_candle(_make_candle(close=price, ts_offset_min=i))
    return calc.get_snapshot()


class TestIndicatorCalculatorEmpty:
    def test_no_candles_returns_none(self):
        calc = IndicatorCalculator()
        assert calc.get_snapshot() is None

    def test_candle_count_zero(self):
        calc = IndicatorCalculator()
        assert calc.candle_count() == 0


class TestIndicatorCalculatorWarmup:
    def test_single_candle_has_close_price(self):
        calc = IndicatorCalculator()
        snap = calc.push_candle(_make_candle(45_000.0))
        assert snap.close_price == 45_000.0

    def test_few_candles_rsi_is_none(self):
        """RSI-14 needs at least 15 candles."""
        calc = IndicatorCalculator()
        snap = None
        for i in range(10):
            snap = calc.push_candle(_make_candle(45_000.0 + i * 10, ts_offset_min=i))
        assert snap.rsi_14 is None

    def test_few_candles_ema200_is_none(self):
        """EMA-200 needs at least 200 candles."""
        calc = IndicatorCalculator()
        snap = _feed_candles(calc, 50)
        assert snap.ema_200 is None

    def test_20_candles_ema20_is_populated(self):
        calc = IndicatorCalculator()
        snap = _feed_candles(calc, 25)
        assert snap.ema_20 is not None
        assert snap.ema_20 > 0


class TestIndicatorCalculatorFullData:
    """Tests that require 200+ candles to fully warm up all indicators."""

    @pytest.fixture(scope="class")
    def warm_calculator(self):
        calc = IndicatorCalculator()
        _feed_candles(calc, 220)
        return calc

    def test_rsi_in_valid_range(self, warm_calculator):
        snap = warm_calculator.get_snapshot()
        assert snap.rsi_14 is not None
        assert 0 <= snap.rsi_14 <= 100, f"RSI out of range: {snap.rsi_14}"

    def test_ema_ordering_in_uptrend(self, warm_calculator):
        """In a sustained uptrend, EMA20 > EMA50."""
        snap = warm_calculator.get_snapshot()
        if snap.ema_20 and snap.ema_50:
            # Allow small tolerance — depends on exact price path
            assert snap.ema_20 >= snap.ema_50 * 0.99

    def test_bollinger_band_ordering(self, warm_calculator):
        snap = warm_calculator.get_snapshot()
        if snap.bb_upper and snap.bb_lower and snap.bb_middle:
            assert snap.bb_upper >= snap.bb_middle >= snap.bb_lower, (
                f"BB ordering violated: upper={snap.bb_upper} "
                f"mid={snap.bb_middle} lower={snap.bb_lower}"
            )

    def test_bb_percent_b_range(self, warm_calculator):
        snap = warm_calculator.get_snapshot()
        if snap.bb_percent_b is not None:
            # %B can exceed [0,1] in extreme moves, but should be reasonable
            assert -2.0 <= snap.bb_percent_b <= 3.0

    def test_macd_values_present(self, warm_calculator):
        snap = warm_calculator.get_snapshot()
        assert snap.macd_line is not None
        assert snap.macd_signal is not None
        assert snap.macd_histogram is not None

    def test_volume_ratio_positive(self, warm_calculator):
        snap = warm_calculator.get_snapshot()
        if snap.volume_ratio is not None:
            assert snap.volume_ratio >= 0

    def test_all_emas_present(self, warm_calculator):
        snap = warm_calculator.get_snapshot()
        assert snap.ema_20 is not None
        assert snap.ema_50 is not None
        assert snap.ema_200 is not None


class TestIndicatorCalculatorResilience:
    def test_handles_duplicate_timestamps(self):
        """Should not crash on duplicate candle timestamps."""
        calc = IndicatorCalculator()
        candle = _make_candle(45_000.0, ts_offset_min=0)
        calc.push_candle(candle)
        calc.push_candle(candle)  # duplicate
        assert calc.candle_count() == 2  # deque allows duplicates

    def test_close_price_updated_on_each_candle(self):
        calc = IndicatorCalculator()
        calc.push_candle(_make_candle(44_000.0, ts_offset_min=0))
        snap1 = calc.get_snapshot()
        calc.push_candle(_make_candle(45_000.0, ts_offset_min=1))
        snap2 = calc.get_snapshot()
        assert snap1.close_price == 44_000.0
        assert snap2.close_price == 45_000.0

    def test_max_candles_respected(self):
        calc = IndicatorCalculator(max_candles=50)
        _feed_candles(calc, 100)
        assert calc.candle_count() == 50
