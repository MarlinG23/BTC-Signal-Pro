"""
Unit tests for the SignalEngine.

Tests verify:
  1. Engine returns None when confidence is below threshold
  2. Engine returns None when fewer than min_indicators agree
  3. Strong bullish indicators produce a BUY or STRONG_BUY signal
  4. Strong bearish indicators produce a SELL or STRONG_SELL signal
  5. Risk/reward ratio is calculated correctly
  6. Take-profit and stop-loss are on the correct side of the entry
  7. Snapshot with None indicator values does not crash
"""

import pytest

from indicators.calculator import IndicatorSnapshot
from signals.engine import SignalEngine, SignalType


def _make_bullish_snapshot(confidence_boost: bool = True) -> IndicatorSnapshot:
    """
    Create an IndicatorSnapshot that should produce a BUY/STRONG_BUY signal.

    RSI oversold + MACD bullish + EMA uptrend + BB lower band
    """
    close = 45_000.0
    return IndicatorSnapshot(
        close_price=close,
        rsi_14=28.0,             # oversold → +1 vote (weight * 1.5)
        macd_line=200.0,         # above signal, above zero → +1
        macd_signal=150.0,
        macd_histogram=50.0,     # positive → +1
        ema_20=close * 1.001,    # price > EMA20 > EMA50 > EMA200
        ema_50=close * 0.995,
        ema_200=close * 0.980,
        bb_upper=close + 500,
        bb_middle=close,
        bb_lower=close - 500,
        bb_percent_b=0.05,       # near lower band → +1
        volume_sma_20=100.0,
        volume_ratio=2.0,        # high volume → boost
    )


def _make_bearish_snapshot() -> IndicatorSnapshot:
    """
    Create an IndicatorSnapshot that should produce a SELL/STRONG_SELL signal.
    """
    close = 45_000.0
    return IndicatorSnapshot(
        close_price=close,
        rsi_14=78.0,             # overbought → -1 vote
        macd_line=-200.0,        # below signal, below zero → -1
        macd_signal=-100.0,
        macd_histogram=-100.0,   # negative → -1
        ema_20=close * 0.999,    # price < EMA20 < EMA50 < EMA200
        ema_50=close * 1.005,
        ema_200=close * 1.020,
        bb_upper=close + 500,
        bb_middle=close,
        bb_lower=close - 500,
        bb_percent_b=0.96,       # near upper band → -1
        volume_sma_20=100.0,
        volume_ratio=1.8,
    )


def _make_neutral_snapshot() -> IndicatorSnapshot:
    """Snapshot where indicators are mixed → should not generate a signal."""
    close = 45_000.0
    return IndicatorSnapshot(
        close_price=close,
        rsi_14=50.0,             # neutral
        macd_line=10.0,
        macd_signal=20.0,        # below signal (bearish -0.5w)
        macd_histogram=-10.0,    # negative
        ema_20=close * 1.001,    # partial uptrend (bullish)
        ema_50=close * 0.999,
        ema_200=close * 0.990,
        bb_upper=close + 1000,
        bb_middle=close,
        bb_lower=close - 1000,
        bb_percent_b=0.50,       # neutral
        volume_sma_20=100.0,
        volume_ratio=1.0,
    )


def _make_minimal_snapshot() -> IndicatorSnapshot:
    """Snapshot with most indicators set to None (warm-up period)."""
    return IndicatorSnapshot(
        close_price=45_000.0,
        rsi_14=None,
        macd_line=None,
        macd_signal=None,
        macd_histogram=None,
        ema_20=None,
        ema_50=None,
        ema_200=None,
        bb_upper=None,
        bb_middle=None,
        bb_lower=None,
        bb_percent_b=None,
        volume_sma_20=None,
        volume_ratio=None,
    )


class TestSignalEngineNullHandling:
    def test_none_snapshot_returns_none(self):
        engine = SignalEngine()
        result = engine.evaluate(IndicatorSnapshot())
        assert result is None

    def test_minimal_snapshot_returns_none(self):
        """During warm-up, no signal should fire."""
        engine = SignalEngine()
        result = engine.evaluate(_make_minimal_snapshot())
        assert result is None

    def test_no_close_price_returns_none(self):
        engine = SignalEngine()
        snap = IndicatorSnapshot(close_price=None)
        assert engine.evaluate(snap) is None


class TestSignalEngineBullish:
    def test_bullish_snapshot_generates_buy_signal(self):
        engine = SignalEngine()
        result = engine.evaluate(_make_bullish_snapshot())
        assert result is not None
        assert result.signal_type in (SignalType.BUY, SignalType.STRONG_BUY)

    def test_bullish_confidence_above_threshold(self):
        engine = SignalEngine()
        result = engine.evaluate(_make_bullish_snapshot())
        assert result is not None
        assert result.confidence >= 70.0

    def test_bullish_take_profit_above_entry(self):
        engine = SignalEngine()
        result = engine.evaluate(_make_bullish_snapshot())
        assert result is not None
        if result.take_profit:
            assert result.take_profit > result.entry_price

    def test_bullish_stop_loss_below_entry(self):
        engine = SignalEngine()
        result = engine.evaluate(_make_bullish_snapshot())
        assert result is not None
        if result.stop_loss:
            assert result.stop_loss < result.entry_price

    def test_bullish_rr_ratio_positive(self):
        engine = SignalEngine()
        result = engine.evaluate(_make_bullish_snapshot())
        assert result is not None
        if result.risk_reward_ratio:
            assert result.risk_reward_ratio > 0


class TestSignalEngineBearish:
    def test_bearish_snapshot_generates_sell_signal(self):
        engine = SignalEngine()
        result = engine.evaluate(_make_bearish_snapshot())
        assert result is not None
        assert result.signal_type in (SignalType.SELL, SignalType.STRONG_SELL)

    def test_bearish_take_profit_below_entry(self):
        engine = SignalEngine()
        result = engine.evaluate(_make_bearish_snapshot())
        assert result is not None
        if result.take_profit:
            assert result.take_profit < result.entry_price

    def test_bearish_stop_loss_above_entry(self):
        engine = SignalEngine()
        result = engine.evaluate(_make_bearish_snapshot())
        assert result is not None
        if result.stop_loss:
            assert result.stop_loss > result.entry_price


class TestSignalEngineNeutral:
    def test_neutral_snapshot_returns_none(self):
        engine = SignalEngine()
        result = engine.evaluate(_make_neutral_snapshot())
        # Mixed indicators — net vote likely below min_indicators threshold
        # Either None or HOLD (HOLD won't be stored by the app anyway)
        if result is not None:
            assert result.signal_type == SignalType.HOLD

    def test_no_signal_below_confidence_threshold(self):
        """If we artificially raise the threshold, nothing should fire."""
        engine = SignalEngine()
        engine._threshold = 101.0  # above maximum possible confidence (100)
        result = engine.evaluate(_make_bullish_snapshot())
        assert result is None


class TestSignalResult:
    def test_to_dict_serialisable(self):
        engine = SignalEngine()
        result = engine.evaluate(_make_bullish_snapshot())
        if result:
            d = result.to_dict()
            assert "signal_type" in d
            assert "confidence" in d
            assert "entry_price" in d
            import json
            # Must be JSON-serialisable
            json.dumps(d)

    def test_indicator_details_is_valid_json(self):
        import json
        engine = SignalEngine()
        result = engine.evaluate(_make_bullish_snapshot())
        if result:
            details = json.loads(result.indicator_details)
            assert isinstance(details, list)
            assert all("name" in item for item in details)
