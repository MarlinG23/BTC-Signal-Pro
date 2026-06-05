"""
Sentiment analyzer for news articles.

Uses VADER (Valence Aware Dictionary and sEntiment Reasoner) which is
optimised for short, informal text like news headlines.  VADER scores
range from -1.0 (most negative) to +1.0 (most positive).

Classification thresholds:
  compound >= 0.10  → BULLISH
  compound <= -0.10 → BEARISH
  else              → NEUTRAL
"""

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

logger = logging.getLogger(__name__)

# Geopolitical keywords that indicate market-moving macro events
GEO_KEYWORDS = frozenset(
    [
        "iran",
        "war",
        "sanctions",
        "fed",
        "federal reserve",
        "interest rate",
        "inflation",
        "recession",
        "russia",
        "china",
        "taiwan",
        "north korea",
        "sec",
        "regulatory",
        "ban",
        "hack",
        "breach",
        "etf",
        "approval",
        "halving",
        "whale",
        "liquidation",
        "crash",
        "rally",
        "ath",
        "all-time high",
    ]
)

# BTC-specific bullish signals in headlines
BTC_BULLISH_TERMS = frozenset(
    ["buy", "bullish", "surge", "soar", "rally", "breakout", "accumulate", "hodl", "moon"]
)

# BTC-specific bearish signals
BTC_BEARISH_TERMS = frozenset(
    ["sell", "bearish", "crash", "dump", "drop", "correction", "fear", "panic", "ban"]
)

SENTIMENT_THRESHOLD_BULLISH = 0.10
SENTIMENT_THRESHOLD_BEARISH = -0.10


class Sentiment(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


@dataclass
class SentimentResult:
    sentiment: Sentiment
    score: float               # -1.0 to +1.0
    is_geopolitical: bool
    geo_keywords_found: list[str]


class SentimentAnalyzer:
    """
    Analyses news article text and classifies its sentiment.

    Initialises the VADER model once and reuses it for all analyses.
    VADER is fast (microseconds per call) so no async needed.
    """

    def __init__(self) -> None:
        try:
            self._vader = SentimentIntensityAnalyzer()
            logger.debug("VADER SentimentIntensityAnalyzer initialised.")
        except Exception as exc:
            logger.error("Failed to initialise VADER: %s", exc)
            self._vader = None

    def analyse(self, title: str, summary: Optional[str] = None) -> SentimentResult:
        """
        Analyse a news article's title (and optional summary) for sentiment.

        Combines VADER scores with BTC-specific keyword boosting for
        more accurate crypto-domain scoring.
        """
        text = title
        if summary:
            # Give title more weight than summary
            text = f"{title} {title} {summary}"

        try:
            score = self._vader_score(text)
            score = self._apply_crypto_boost(text, score)
        except Exception as exc:
            logger.warning("Sentiment analysis error for '%s': %s", title[:50], exc)
            score = 0.0

        # Classify
        if score >= SENTIMENT_THRESHOLD_BULLISH:
            sentiment = Sentiment.BULLISH
        elif score <= SENTIMENT_THRESHOLD_BEARISH:
            sentiment = Sentiment.BEARISH
        else:
            sentiment = Sentiment.NEUTRAL

        # Geopolitical detection
        geo_found = self._detect_geo_keywords(text)

        return SentimentResult(
            sentiment=sentiment,
            score=round(score, 4),
            is_geopolitical=len(geo_found) > 0,
            geo_keywords_found=geo_found,
        )

    # ── Private helpers ───────────────────────────────────────────────────

    def _vader_score(self, text: str) -> float:
        """Return the VADER compound score for text, or 0.0 on failure."""
        if not self._vader:
            return 0.0
        scores = self._vader.polarity_scores(text)
        return float(scores["compound"])

    def _apply_crypto_boost(self, text: str, score: float) -> float:
        """
        Apply a small boost/penalty based on BTC-specific terminology.

        This corrects for VADER's general-purpose training data not
        including crypto slang (e.g. "moon", "HODL", "pump").
        """
        lower = text.lower()
        words = set(re.findall(r"\b\w+\b", lower))

        bullish_hits = len(words & BTC_BULLISH_TERMS)
        bearish_hits = len(words & BTC_BEARISH_TERMS)

        boost = (bullish_hits - bearish_hits) * 0.05
        return max(-1.0, min(1.0, score + boost))

    def _detect_geo_keywords(self, text: str) -> list[str]:
        """Return a list of geopolitical keywords found in the text."""
        lower = text.lower()
        found: list[str] = []
        for kw in GEO_KEYWORDS:
            if kw in lower:
                found.append(kw)
        return found
