"""
News fetcher for BTC Signal Pro — Phase 3.

Fetches news from verified sources:
  1. CoinDesk RSS feed
  2. Reuters RSS feed (business / tech headlines)
  3. Fear & Greed Index (alternative.me API — no key required)
  4. Glassnode on-chain metrics (requires API key)
  5. CoinGlass liquidation data (requires API key)

All network calls use httpx with retry logic (3 attempts, exponential back-off).
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import feedparser
import httpx

from config import settings

logger = logging.getLogger(__name__)

# Source identifiers
SOURCE_COINDESK = "coindesk"
SOURCE_COINTELEGRAPH = "cointelegraph"
SOURCE_BITCOIN_MAGAZINE = "bitcoin_magazine"
SOURCE_FEAR_GREED = "fear_greed"
SOURCE_GLASSNODE = "glassnode"
SOURCE_COINGLASS = "coinglass"

# RSS feed URLs — Reuters removed (requires auth / 401), replaced with
# CoinTelegraph and Bitcoin Magazine which return 200 with full content
COINDESK_RSS = "https://www.coindesk.com/arc/outboundfeeds/rss/"
COINTELEGRAPH_RSS = "https://cointelegraph.com/rss"
BITCOIN_MAGAZINE_RSS = "https://bitcoinmagazine.com/feed"

# REST API URLs
FEAR_GREED_API = "https://api.alternative.me/fng/?limit=1&format=json"
GLASSNODE_API = "https://api.glassnode.com/v1/metrics/market/price_usd_close"
COINGLASS_API = "https://open-api.coinglass.com/public/v2/liquidation_history"

MAX_RETRIES = 3
RETRY_DELAY_S = 2.0


@dataclass
class RawArticle:
    """A news article before sentiment analysis and fake-news filtering."""

    source: str
    title: str
    url: str
    published_at: Optional[datetime] = None
    summary: Optional[str] = None


@dataclass
class FearGreedData:
    """Fear & Greed Index data point."""

    value: int          # 0–100
    classification: str  # "Extreme Fear" | "Fear" | "Neutral" | "Greed" | "Extreme Greed"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class LiquidationData:
    """Liquidation summary for BTC from CoinGlass."""

    long_liquidations_usd: float
    short_liquidations_usd: float
    total_liquidations_usd: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class NewsFetcher:
    """
    Fetches news and market data from all verified sources concurrently.

    All fetch methods handle errors gracefully — a failed source returns
    an empty list rather than crashing the application.
    """

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "NewsFetcher":
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0),
            follow_redirects=True,
            headers={"User-Agent": "BTC-Signal-Pro/1.0"},
        )
        return self

    async def __aexit__(self, *args) -> None:
        if self._client:
            await self._client.aclose()

    # ── Public API ────────────────────────────────────────────────────────

    async def fetch_all_news(self) -> list[RawArticle]:
        """
        Fetch articles from CoinDesk, CoinTelegraph, and Bitcoin Magazine
        concurrently.  Returns a deduplicated list sorted newest-first.
        """
        results = await asyncio.gather(
            self.fetch_coindesk(),
            self.fetch_cointelegraph(),
            self.fetch_bitcoin_magazine(),
            return_exceptions=True,
        )

        articles: list[RawArticle] = []
        for result in results:
            if isinstance(result, Exception):
                logger.error("News fetch error: %s", result)
            elif isinstance(result, list):
                articles.extend(result)

        # Deduplicate by URL
        seen_urls: set[str] = set()
        unique: list[RawArticle] = []
        for a in articles:
            if a.url not in seen_urls:
                seen_urls.add(a.url)
                unique.append(a)

        # Sort newest first
        unique.sort(
            key=lambda a: a.published_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return unique

    async def fetch_coindesk(self) -> list[RawArticle]:
        """Fetch latest headlines from CoinDesk RSS feed."""
        return await self._fetch_rss(SOURCE_COINDESK, COINDESK_RSS)

    async def fetch_cointelegraph(self) -> list[RawArticle]:
        """Fetch latest headlines from CoinTelegraph RSS feed."""
        return await self._fetch_rss(SOURCE_COINTELEGRAPH, COINTELEGRAPH_RSS)

    async def fetch_bitcoin_magazine(self) -> list[RawArticle]:
        """Fetch latest headlines from Bitcoin Magazine RSS feed."""
        return await self._fetch_rss(SOURCE_BITCOIN_MAGAZINE, BITCOIN_MAGAZINE_RSS)

    async def fetch_fear_greed(self) -> Optional[FearGreedData]:
        """
        Fetch the current Fear & Greed Index from alternative.me.

        Returns None if the API is unreachable.
        """
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = await self._client.get(FEAR_GREED_API)
                resp.raise_for_status()
                data = resp.json()
                fg = data["data"][0]
                return FearGreedData(
                    value=int(fg["value"]),
                    classification=fg["value_classification"],
                    timestamp=datetime.fromtimestamp(int(fg["timestamp"]), tz=timezone.utc),
                )
            except Exception as exc:
                logger.warning("Fear & Greed fetch attempt %d failed: %s", attempt, exc)
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_DELAY_S ** attempt)
        return None

    async def fetch_glassnode_price(self) -> Optional[float]:
        """
        Fetch latest BTC close price from Glassnode (requires API key).

        Returns the close price or None on failure.
        """
        if not settings.GLASSNODE_API_KEY:
            logger.debug("GLASSNODE_API_KEY not set — skipping Glassnode fetch.")
            return None

        params = {
            "a": "BTC",
            "api_key": settings.GLASSNODE_API_KEY,
            "i": "24h",
            "f": "JSON",
        }
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = await self._client.get(GLASSNODE_API, params=params)
                resp.raise_for_status()
                data = resp.json()
                # API returns list of {"t": unix_ts, "v": price}
                if data:
                    return float(data[-1]["v"])
            except Exception as exc:
                logger.warning("Glassnode fetch attempt %d failed: %s", attempt, exc)
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_DELAY_S ** attempt)
        return None

    async def fetch_coinglass_liquidations(self) -> Optional[LiquidationData]:
        """
        Fetch recent BTC liquidation data from CoinGlass.

        Returns None if the API is unreachable or key is missing.
        """
        if not settings.COINGLASS_API_KEY:
            logger.debug("COINGLASS_API_KEY not set — skipping CoinGlass fetch.")
            return None

        headers = {"coinglassSecret": settings.COINGLASS_API_KEY}
        params = {"symbol": "BTC", "time_type": "h1"}

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = await self._client.get(
                    COINGLASS_API, headers=headers, params=params
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("success") and data.get("data"):
                    latest = data["data"][-1]
                    long_liq = float(latest.get("longLiquidationUsd", 0))
                    short_liq = float(latest.get("shortLiquidationUsd", 0))
                    return LiquidationData(
                        long_liquidations_usd=long_liq,
                        short_liquidations_usd=short_liq,
                        total_liquidations_usd=long_liq + short_liq,
                    )
            except Exception as exc:
                logger.warning("CoinGlass fetch attempt %d failed: %s", attempt, exc)
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_DELAY_S ** attempt)
        return None

    # ── Private helpers ───────────────────────────────────────────────────

    async def _fetch_rss(self, source: str, url: str) -> list[RawArticle]:
        """
        Fetch and parse an RSS feed.

        feedparser is synchronous, so we run it in the default thread
        executor to avoid blocking the event loop.
        """
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = await self._client.get(url)
                resp.raise_for_status()
                raw_xml = resp.text

                # Parse in thread to keep event loop free
                loop = asyncio.get_event_loop()
                feed = await loop.run_in_executor(None, feedparser.parse, raw_xml)

                articles: list[RawArticle] = []
                for entry in feed.entries[:20]:  # limit to 20 most recent
                    pub = None
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        from calendar import timegm
                        pub = datetime.fromtimestamp(timegm(entry.published_parsed), tz=timezone.utc)

                    articles.append(
                        RawArticle(
                            source=source,
                            title=entry.get("title", "").strip(),
                            url=entry.get("link", "").strip(),
                            published_at=pub,
                            summary=entry.get("summary", "").strip(),
                        )
                    )
                logger.debug("Fetched %d articles from %s", len(articles), source)
                return articles

            except Exception as exc:
                logger.warning("%s RSS fetch attempt %d failed: %s", source, attempt, exc)
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_DELAY_S ** attempt)

        return []
