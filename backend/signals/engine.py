"""
Signal Engine — Phase 2

Consumes IndicatorSnapshot objects and produces trading signals.

Signal generation rules:
  1. Each technical indicator casts a "vote": +1 (bullish), -1 (bearish), or 0 (neutral).
  2. A signal fires only if the absolute vote count >= SIGNAL_MIN_INDICATORS.
  3. Confidence is calculated as a weighted score (0–100%).
  4. Only signals with confidence >= SIGNAL_CONFIDENCE_THRESHOLD are returned.
  5. Entry, take-profit, and stop-loss are calculated from ATR(14).
  6. Risk/reward ratio is computed as |TP - entry| / |entry - SL|.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from indicators.calculator import IndicatorSnapshot
from config import settings

logger = logging.getLogger(__name__)


class SignalType(str, Enum):
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"


@dataclass
class IndicatorVote:
    """A single indicator's contribution to the final signal."""

    name: str
    direction: int  # +1 = bullish, -1 = bearish, 0 = neutral
    weight: float   # 0.0–1.0 — how much this vote counts toward confidence
    reason: str     # human-readable explanation


@dataclass
class SignalResult:
    """
    A fully-computed trading signal ready for storage and alerting.
    """

    signal_type: SignalType
    confidence: float  # 0–100
    entry_price: float
    take_profit: Optional[float]
    stop_loss: Optional[float]
    risk_reward_ratio: Optional[float]
    indicators_agreed: int
    indicator_details: str  # JSON string of IndicatorVote list
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "signal_type": self.signal_type.value,
            "confidence": round(self.confidence, 2),
            "entry_price": self.entry_price,
            "take_profit": self.take_profit,
            "stop_loss": self.stop_loss,
            "risk_reward_ratio": self.risk_reward_ratio,
            "indicators_agreed": self.indicators_agreed,
            "generated_at": self.generated_at.isoformat(),
        }


class SignalEngine:
    """
    Evaluates a snapshot of indicator values and produces a SignalResult.

    Instantiate once and call evaluate() on every new IndicatorSnapshot.
    Only returns a SignalResult when the signal clears the confidence threshold.
    """

    # Indicator weights — higher weight = stronger influence on confidence
    WEIGHTS = {
        "rsi": 0.20,
        "macd": 0.20,
        "ema_trend": 0.25,   # EMAs 20/50/200 relative positions
        "bollinger": 0.15,
        "volume": 0.10,
        "macd_histogram": 0.10,
    }

    # Risk:Reward targets per signal strength
    TP_MULTIPLIERS = {
        SignalType.STRONG_BUY: 3.0,
        SignalType.BUY: 2.0,
        SignalType.SELL: 2.0,
        SignalType.STRONG_SELL: 3.0,
        SignalType.HOLD: 1.0,
    }
    SL_MULTIPLIERS = {
        SignalType.STRONG_BUY: 1.0,
        SignalType.BUY: 1.0,
        SignalType.SELL: 1.0,
        SignalType.STRONG_SELL: 1.0,
        SignalType.HOLD: 1.0,
    }

    def __init__(
        self,
        *,
        confidence_threshold: Optional[float] = None,
        min_indicators: Optional[int] = None,
        min_tp_pct: float = 0.005,
        min_sl_pct: float = 0.003,
    ) -> None:
        self._threshold = (
            confidence_threshold
            if confidence_threshold is not None
            else settings.SIGNAL_CONFIDENCE_THRESHOLD
        )
        self._min_indicators = (
            min_indicators
            if min_indicators is not None
            else settings.SIGNAL_MIN_INDICATORS
        )
        self._min_candles = settings.SIGNAL_MIN_CANDLES
        self._min_tp_pct = min_tp_pct
        self._min_sl_pct = min_sl_pct

    # ── Public API ────────────────────────────────────────────────────────

    def evaluate(
        self, snapshot: IndicatorSnapshot, candle_count: int = 999
    ) -> Optional[SignalResult]:
        """
        Evaluate an indicator snapshot.

        Returns a SignalResult if a tradeable signal is detected above the
        confidence threshold, otherwise returns None.

        candle_count: number of candles in the rolling window — evaluation
        is skipped below SIGNAL_MIN_CANDLES to avoid noise on cold start.
        """
        if snapshot.close_price is None:
            return None
        if candle_count < self._min_candles:
            return None

        try:
            votes = self._cast_votes(snapshot)
            return self._build_signal(snapshot, votes)
        except Exception as exc:
            logger.error("Signal evaluation error: %s", exc, exc_info=True)
            return None

    # ── Vote casters ──────────────────────────────────────────────────────

    def _cast_votes(self, snap: IndicatorSnapshot) -> list[IndicatorVote]:
        """Collect a vote from each available indicator."""
        votes: list[IndicatorVote] = []

        v = self._vote_rsi(snap)
        if v:
            votes.append(v)

        v = self._vote_macd(snap)
        if v:
            votes.append(v)

        v = self._vote_macd_histogram(snap)
        if v:
            votes.append(v)

        v = self._vote_ema_trend(snap)
        if v:
            votes.append(v)

        v = self._vote_bollinger(snap)
        if v:
            votes.append(v)

        v = self._vote_volume(snap)
        if v:
            votes.append(v)

        return votes

    def _vote_rsi(self, snap: IndicatorSnapshot) -> Optional[IndicatorVote]:
        """
        RSI thresholds:
          < 30  → oversold  (strong bullish)
          30–40 → recovering (mild bullish)
          60–70 → approaching overbought (mild bearish)
          > 70  → overbought (strong bearish)
          else  → neutral
        """
        if snap.rsi_14 is None:
            return None

        rsi = snap.rsi_14
        if rsi < 25:
            return IndicatorVote("rsi", +1, self.WEIGHTS["rsi"] * 1.5, f"RSI={rsi:.1f} extremely oversold")
        if rsi < 35:
            return IndicatorVote("rsi", +1, self.WEIGHTS["rsi"], f"RSI={rsi:.1f} oversold")
        if rsi > 75:
            return IndicatorVote("rsi", -1, self.WEIGHTS["rsi"] * 1.5, f"RSI={rsi:.1f} extremely overbought")
        if rsi > 65:
            return IndicatorVote("rsi", -1, self.WEIGHTS["rsi"], f"RSI={rsi:.1f} overbought")
        return IndicatorVote("rsi", 0, self.WEIGHTS["rsi"], f"RSI={rsi:.1f} neutral")

    def _vote_macd(self, snap: IndicatorSnapshot) -> Optional[IndicatorVote]:
        """
        MACD line crossing above/below signal line.
        Positive histogram AND macd_line > 0 → bullish momentum.
        """
        if snap.macd_line is None or snap.macd_signal is None:
            return None

        if snap.macd_line > snap.macd_signal and snap.macd_line > 0:
            return IndicatorVote(
                "macd", +1, self.WEIGHTS["macd"],
                f"MACD={snap.macd_line:.2f} above signal above zero"
            )
        if snap.macd_line > snap.macd_signal and snap.macd_line < 0:
            return IndicatorVote(
                "macd", +1, self.WEIGHTS["macd"] * 0.5,
                f"MACD={snap.macd_line:.2f} above signal but below zero"
            )
        if snap.macd_line < snap.macd_signal and snap.macd_line < 0:
            return IndicatorVote(
                "macd", -1, self.WEIGHTS["macd"],
                f"MACD={snap.macd_line:.2f} below signal below zero"
            )
        if snap.macd_line < snap.macd_signal and snap.macd_line > 0:
            return IndicatorVote(
                "macd", -1, self.WEIGHTS["macd"] * 0.5,
                f"MACD={snap.macd_line:.2f} below signal but above zero"
            )
        return IndicatorVote("macd", 0, self.WEIGHTS["macd"], "MACD neutral crossover")

    def _vote_macd_histogram(self, snap: IndicatorSnapshot) -> Optional[IndicatorVote]:
        """Histogram trend: rising bullish bars → accumulation signal."""
        if snap.macd_histogram is None:
            return None

        hist = snap.macd_histogram
        if hist > 0:
            return IndicatorVote("macd_histogram", +1, self.WEIGHTS["macd_histogram"],
                                 f"MACD histogram={hist:.2f} positive")
        if hist < 0:
            return IndicatorVote("macd_histogram", -1, self.WEIGHTS["macd_histogram"],
                                 f"MACD histogram={hist:.2f} negative")
        return IndicatorVote("macd_histogram", 0, self.WEIGHTS["macd_histogram"], "MACD histogram flat")

    def _vote_ema_trend(self, snap: IndicatorSnapshot) -> Optional[IndicatorVote]:
        """
        EMA alignment:
          price > EMA20 > EMA50 > EMA200 → strong uptrend (bullish)
          price < EMA20 < EMA50 < EMA200 → strong downtrend (bearish)
          Mixed alignment → neutral
        """
        if None in (snap.close_price, snap.ema_20, snap.ema_50, snap.ema_200):
            return None

        p, e20, e50, e200 = snap.close_price, snap.ema_20, snap.ema_50, snap.ema_200

        if p > e20 > e50 > e200:
            return IndicatorVote("ema_trend", +1, self.WEIGHTS["ema_trend"],
                                 "Perfect EMA uptrend: price > EMA20 > EMA50 > EMA200")
        if p < e20 < e50 < e200:
            return IndicatorVote("ema_trend", -1, self.WEIGHTS["ema_trend"],
                                 "Perfect EMA downtrend: price < EMA20 < EMA50 < EMA200")
        if p > e20 and e20 > e50:
            return IndicatorVote("ema_trend", +1, self.WEIGHTS["ema_trend"] * 0.6,
                                 "Partial EMA uptrend: price > EMA20 > EMA50")
        if p < e20 and e20 < e50:
            return IndicatorVote("ema_trend", -1, self.WEIGHTS["ema_trend"] * 0.6,
                                 "Partial EMA downtrend: price < EMA20 < EMA50")
        return IndicatorVote("ema_trend", 0, self.WEIGHTS["ema_trend"], "EMA mixed/neutral")

    def _vote_bollinger(self, snap: IndicatorSnapshot) -> Optional[IndicatorVote]:
        """
        Bollinger %B position:
          %B < 0.05  → price near/below lower band → oversold reversal signal
          %B > 0.95  → price near/above upper band → overbought reversal signal
          %B < 0.20  → approaching lower band → mildly bullish
          %B > 0.80  → approaching upper band → mildly bearish
        """
        if snap.bb_percent_b is None or snap.close_price is None:
            return None

        pb = snap.bb_percent_b
        if pb < 0.05:
            return IndicatorVote("bollinger", +1, self.WEIGHTS["bollinger"] * 1.3,
                                 f"BB %B={pb:.2f} — price at/below lower band (oversold)")
        if pb < 0.20:
            return IndicatorVote("bollinger", +1, self.WEIGHTS["bollinger"],
                                 f"BB %B={pb:.2f} — approaching lower band")
        if pb > 0.95:
            return IndicatorVote("bollinger", -1, self.WEIGHTS["bollinger"] * 1.3,
                                 f"BB %B={pb:.2f} — price at/above upper band (overbought)")
        if pb > 0.80:
            return IndicatorVote("bollinger", -1, self.WEIGHTS["bollinger"],
                                 f"BB %B={pb:.2f} — approaching upper band")
        return IndicatorVote("bollinger", 0, self.WEIGHTS["bollinger"],
                             f"BB %B={pb:.2f} — mid-band neutral")

    def _vote_volume(self, snap: IndicatorSnapshot) -> Optional[IndicatorVote]:
        """
        Volume confirmation:
          ratio > 1.5 amplifies the directional signal (volume confirms move)
          ratio < 0.5 weakens the signal (low-volume / unreliable move)
        """
        if snap.volume_ratio is None:
            return None

        ratio = snap.volume_ratio
        # Volume alone is directionally neutral; it modifies confidence
        if ratio >= 1.5:
            return IndicatorVote("volume", 0, self.WEIGHTS["volume"],
                                 f"High volume confirmation (ratio={ratio:.2f})")
        if ratio <= 0.5:
            return IndicatorVote("volume", 0, -self.WEIGHTS["volume"] * 0.5,
                                 f"Low volume warning (ratio={ratio:.2f})")
        return IndicatorVote("volume", 0, 0.0, f"Average volume (ratio={ratio:.2f})")

    # ── Signal builder ────────────────────────────────────────────────────

    def _build_signal(
        self, snap: IndicatorSnapshot, votes: list[IndicatorVote]
    ) -> Optional[SignalResult]:
        """
        Aggregate votes into a final signal.

        Confidence = weighted_bullish_score / total_possible_weight × 100
        The direction (buy vs sell) is determined by the net vote count.
        """
        bullish_weight = sum(v.weight for v in votes if v.direction == +1)
        bearish_weight = sum(v.weight for v in votes if v.direction == -1)
        total_weight = sum(abs(v.weight) for v in votes if v.direction != 0)

        bullish_count = sum(1 for v in votes if v.direction == +1)
        bearish_count = sum(1 for v in votes if v.direction == -1)

        net_bullish = bullish_count - bearish_count
        abs_net = abs(net_bullish)

        # Not enough indicators agree → no signal
        if abs_net < self._min_indicators:
            return None

        # Normalise confidence to 0–100
        if total_weight > 0:
            if net_bullish > 0:
                raw_conf = (bullish_weight / total_weight) * 100
            else:
                raw_conf = (bearish_weight / total_weight) * 100
        else:
            raw_conf = 0.0

        # Volume boost / penalty
        vol_vote = next((v for v in votes if v.name == "volume"), None)
        if vol_vote and vol_vote.weight > 0 and abs(net_bullish) >= 3:
            raw_conf = min(100.0, raw_conf * 1.1)  # 10% volume confirmation boost
        elif vol_vote and vol_vote.weight < 0:
            raw_conf *= 0.85  # 15% low-volume penalty

        confidence = min(100.0, max(0.0, raw_conf))

        # Below threshold → skip
        if confidence < self._threshold:
            return None

        # Map to signal type based on net vote count and confidence
        signal_type = self._classify_signal(net_bullish, confidence)

        # Compute price levels from ATR(14)
        entry = snap.close_price
        tp, sl = self._compute_levels(signal_type, entry, snap.atr_14)
        rr = self._compute_rr(signal_type, entry, tp, sl)

        details = json.dumps(
            [{"name": v.name, "direction": v.direction, "reason": v.reason} for v in votes]
        )

        logger.info(
            "Signal generated: %s conf=%.1f%% entry=%.2f TP=%.2f SL=%.2f",
            signal_type.value, confidence, entry, tp or 0, sl or 0,
        )

        return SignalResult(
            signal_type=signal_type,
            confidence=confidence,
            entry_price=entry,
            take_profit=tp,
            stop_loss=sl,
            risk_reward_ratio=rr,
            indicators_agreed=abs_net,
            indicator_details=details,
        )

    def _classify_signal(self, net_bullish: int, confidence: float) -> SignalType:
        """Translate net vote count + confidence into a discrete signal type."""
        if net_bullish >= 4 and confidence >= 85:
            return SignalType.STRONG_BUY
        if net_bullish >= 3 and confidence >= 70:
            return SignalType.BUY
        if net_bullish <= -4 and confidence >= 85:
            return SignalType.STRONG_SELL
        if net_bullish <= -3 and confidence >= 70:
            return SignalType.SELL
        return SignalType.HOLD

    def _compute_levels(
        self, signal_type: SignalType, entry: float, atr_14: Optional[float]
    ) -> tuple[Optional[float], Optional[float]]:
        """
        Calculate take-profit and stop-loss from ATR(14).

        TP distance = max(ATR × 2, 0.5% of entry)
        SL distance = max(ATR × 1, 0.3% of entry)
        """
        min_tp_dist = entry * self._min_tp_pct
        min_sl_dist = entry * self._min_sl_pct

        if atr_14 is not None and atr_14 > 0:
            tp_from_atr = atr_14 * 2
            sl_from_atr = atr_14 * 1
            tp_dist = max(tp_from_atr, min_tp_dist)
            sl_dist = max(sl_from_atr, min_sl_dist)
        else:
            tp_dist = min_tp_dist
            sl_dist = min_sl_dist

        if signal_type in (SignalType.STRONG_BUY, SignalType.BUY):
            tp = round(entry + tp_dist, 2)
            sl = round(entry - sl_dist, 2)
        elif signal_type in (SignalType.STRONG_SELL, SignalType.SELL):
            tp = round(entry - tp_dist, 2)
            sl = round(entry + sl_dist, 2)
        else:
            tp = sl = None

        return tp, sl

    def _compute_rr(
        self,
        signal_type: SignalType,
        entry: float,
        tp: Optional[float],
        sl: Optional[float],
    ) -> Optional[float]:
        """Risk/reward ratio = |potential gain| / |potential loss|."""
        if tp is None or sl is None:
            return None
        potential_gain = abs(tp - entry)
        potential_loss = abs(entry - sl)
        if potential_loss == 0:
            return None
        return round(potential_gain / potential_loss, 2)
