"""Shared trend-following direction used by the live 4H gate, MTF confluence,
the backtester, and (mirrored in) the frontend deriveTrend().

Aggressive / profit-seeking rule:
  Bullish (+1): price > EMA20 > EMA50  — RSI may be overbought in a melt-up
  Bearish (-1): price < EMA20 < EMA50
  Neutral  (0): mixed stack or insufficient data

The old RSI<70 / RSI>30 veto labeled strong bull runs as NEUTRAL and
blocked the BUY signals this app is built to fire.
"""

from typing import Optional

from indicators.calculator import IndicatorSnapshot


def trend_direction_from_snapshot(snap: Optional[IndicatorSnapshot]) -> int:
    """Return +1 (bullish), -1 (bearish), or 0 (neutral/insufficient data)."""
    if snap is None or snap.close_price is None:
        return 0

    p = snap.close_price
    e20 = snap.ema_20
    e50 = snap.ema_50

    if None in (e20, e50):
        return 0

    if p > e20 > e50:
        return +1
    if p < e20 < e50:
        return -1
    return 0
