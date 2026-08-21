"""Unit tests for aggressive trend-following direction."""

from datetime import datetime, timezone

from indicators.calculator import IndicatorSnapshot
from signals.trend import trend_direction_from_snapshot


def _snap(**kwargs) -> IndicatorSnapshot:
    defaults = dict(
        timestamp=datetime.now(timezone.utc),
        close_price=75000.0,
        rsi_14=50.0,
        macd_line=0.0,
        macd_signal=0.0,
        macd_histogram=0.0,
        ema_20=74000.0,
        ema_50=72000.0,
        ema_200=68000.0,
        bb_upper=76000.0,
        bb_middle=74000.0,
        bb_lower=72000.0,
        bb_percent_b=0.5,
        volume_sma_20=100.0,
        volume_ratio=1.0,
        atr_14=100.0,
    )
    defaults.update(kwargs)
    return IndicatorSnapshot(**defaults)


def test_overbought_uptrend_is_bullish():
    """A melt-up with RSI 92 must still be BULLISH so BUY can fire."""
    snap = _snap(
        close_price=74575.0,
        ema_20=68821.0,
        ema_50=66308.0,
        rsi_14=92.3,
    )
    assert trend_direction_from_snapshot(snap) == +1


def test_oversold_downtrend_is_bearish():
    snap = _snap(
        close_price=60000.0,
        ema_20=62000.0,
        ema_50=64000.0,
        rsi_14=18.0,
    )
    assert trend_direction_from_snapshot(snap) == -1


def test_mixed_emas_are_neutral():
    snap = _snap(close_price=70000.0, ema_20=71000.0, ema_50=69000.0, rsi_14=55.0)
    assert trend_direction_from_snapshot(snap) == 0


def test_missing_snapshot_is_neutral():
    assert trend_direction_from_snapshot(None) == 0
