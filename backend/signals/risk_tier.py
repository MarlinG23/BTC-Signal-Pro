"""RSI-based risk tier for live signals.

Does not change whether a BUY/SELL fires. Scales position size and TP/SL
distance from 4H RSI at the moment of entry so extended markets still
participate, but with less size and tighter targets.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from signals.engine import SignalResult


@dataclass(frozen=True)
class RiskTier:
    tier: int
    size_multiplier: float
    tp_multiplier: float
    sl_multiplier: float

    def to_dict(self) -> dict:
        return {
            "risk_tier": self.tier,
            "size_multiplier": self.size_multiplier,
            "tp_multiplier": self.tp_multiplier,
            "sl_multiplier": self.sl_multiplier,
        }


def get_risk_tier(rsi_4h: Optional[float]) -> RiskTier:
    """Map 4H RSI to a risk tier. Missing RSI → full-size Tier 1."""
    if rsi_4h is None or rsi_4h < 70:
        return RiskTier(
            tier=1, size_multiplier=1.0, tp_multiplier=1.0, sl_multiplier=1.0
        )
    if rsi_4h < 85:
        return RiskTier(
            tier=2, size_multiplier=0.5, tp_multiplier=0.6, sl_multiplier=0.7
        )
    return RiskTier(
        tier=3, size_multiplier=0.25, tp_multiplier=0.4, sl_multiplier=0.5
    )


def scale_levels(
    signal_type: str,
    entry: float,
    take_profit: Optional[float],
    stop_loss: Optional[float],
    tier: RiskTier,
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Return (tp, sl, rr) with distances scaled by the tier multipliers."""
    if take_profit is None or stop_loss is None or entry <= 0:
        return take_profit, stop_loss, None

    tp_dist = abs(take_profit - entry) * tier.tp_multiplier
    sl_dist = abs(entry - stop_loss) * tier.sl_multiplier
    is_long = signal_type in ("BUY", "STRONG_BUY")

    if is_long:
        tp = round(entry + tp_dist, 2)
        sl = round(entry - sl_dist, 2)
    else:
        tp = round(entry - tp_dist, 2)
        sl = round(entry + sl_dist, 2)

    rr = round(tp_dist / sl_dist, 2) if sl_dist > 0 else None
    return tp, sl, rr


def attach_risk_tier(signal: "SignalResult", rsi_4h: Optional[float]) -> RiskTier:
    """Stamp 4H RSI onto every signal. Scale TP/SL/size on BUY only (first pass)."""
    signal.rsi_4h = rsi_4h

    if signal.signal_type.value not in ("BUY", "STRONG_BUY"):
        tier = RiskTier(
            tier=1, size_multiplier=1.0, tp_multiplier=1.0, sl_multiplier=1.0
        )
        signal.risk_tier = tier.tier
        signal.size_multiplier = tier.size_multiplier
        signal.tp_multiplier = tier.tp_multiplier
        signal.sl_multiplier = tier.sl_multiplier
        return tier

    tier = get_risk_tier(rsi_4h)
    signal.risk_tier = tier.tier
    signal.size_multiplier = tier.size_multiplier
    signal.tp_multiplier = tier.tp_multiplier
    signal.sl_multiplier = tier.sl_multiplier
    tp, sl, rr = scale_levels(
        signal.signal_type.value,
        signal.entry_price,
        signal.take_profit,
        signal.stop_loss,
        tier,
    )
    signal.take_profit = tp
    signal.stop_loss = sl
    if rr is not None:
        signal.risk_reward_ratio = rr
    return tier
