"""Unit tests for 4H RSI risk tiers."""

from signals.engine import SignalResult, SignalType
from signals.risk_tier import get_risk_tier, scale_levels, attach_risk_tier


def test_tier1_below_70():
    t = get_risk_tier(69.9)
    assert t.tier == 1
    assert t.size_multiplier == 1.0
    assert t.tp_multiplier == 1.0
    assert t.sl_multiplier == 1.0


def test_tier1_missing_rsi():
    assert get_risk_tier(None).tier == 1


def test_tier2_between_70_and_85():
    t = get_risk_tier(70.0)
    assert t.tier == 2
    assert t.size_multiplier == 0.5
    assert t.tp_multiplier == 0.6
    assert t.sl_multiplier == 0.7
    assert get_risk_tier(84.9).tier == 2


def test_tier3_at_or_above_85():
    t = get_risk_tier(85.0)
    assert t.tier == 3
    assert t.size_multiplier == 0.25
    assert t.tp_multiplier == 0.4
    assert t.sl_multiplier == 0.5
    assert get_risk_tier(92.3).tier == 3


def test_scale_levels_tightens_buy_tp_sl():
    entry = 75_000.0
    tp, sl, rr = scale_levels("BUY", entry, 75_400.0, 74_700.0, get_risk_tier(92.3))
    assert tp == round(entry + 400 * 0.4, 2)
    assert sl == round(entry - 300 * 0.5, 2)
    assert rr == round((400 * 0.4) / (300 * 0.5), 2)


def test_scale_levels_tier1_unchanged():
    entry = 75_000.0
    tp, sl, rr = scale_levels("BUY", entry, 75_400.0, 74_700.0, get_risk_tier(50.0))
    assert tp == 75_400.0
    assert sl == 74_700.0
    assert rr == round(400 / 300, 2)


def _buy_signal() -> SignalResult:
    return SignalResult(
        signal_type=SignalType.BUY,
        confidence=85.0,
        entry_price=75_000.0,
        take_profit=75_400.0,
        stop_loss=74_700.0,
        risk_reward_ratio=1.33,
        indicators_agreed=3,
        indicator_details="[]",
    )


def test_attach_risk_tier_scales_buy_at_rsi_92():
    sig = _buy_signal()
    attach_risk_tier(sig, 92.3)
    assert sig.risk_tier == 3
    assert sig.rsi_4h == 92.3
    assert sig.size_multiplier == 0.25
    assert sig.take_profit == round(75_000 + 400 * 0.4, 2)
    assert sig.stop_loss == round(75_000 - 300 * 0.5, 2)


def test_attach_risk_tier_does_not_scale_sell():
    sig = SignalResult(
        signal_type=SignalType.SELL,
        confidence=85.0,
        entry_price=75_000.0,
        take_profit=74_600.0,
        stop_loss=75_300.0,
        risk_reward_ratio=1.33,
        indicators_agreed=3,
        indicator_details="[]",
    )
    attach_risk_tier(sig, 92.3)
    assert sig.risk_tier == 1
    assert sig.rsi_4h == 92.3
    assert sig.take_profit == 74_600.0
    assert sig.stop_loss == 75_300.0

