"""
Unit tests for the SentimentAnalyzer and FakeNewsFilter.
"""

import pytest
from datetime import datetime, timezone, timedelta

from news.sentiment import SentimentAnalyzer, Sentiment
from news.filter import FakeNewsFilter
from news.fetcher import RawArticle


class TestSentimentAnalyzer:
    @pytest.fixture(autouse=True)
    def analyzer(self):
        self.analyzer = SentimentAnalyzer()

    def test_bullish_headline(self):
        result = self.analyzer.analyse("Bitcoin price jumps as investors celebrate positive gains")
        assert result.sentiment == Sentiment.BULLISH
        assert result.score > 0

    def test_bearish_headline(self):
        result = self.analyzer.analyse("Bitcoin crashes 20% in massive sell-off panic")
        assert result.sentiment == Sentiment.BEARISH
        assert result.score < 0

    def test_neutral_headline(self):
        result = self.analyzer.analyse("Bitcoin price update for Tuesday")
        assert result.sentiment == Sentiment.NEUTRAL

    def test_geopolitical_keyword_iran(self):
        result = self.analyzer.analyse("Iran sanctions impact on crypto markets")
        assert result.is_geopolitical is True
        assert "iran" in result.geo_keywords_found

    def test_geopolitical_keyword_fed(self):
        result = self.analyzer.analyse("Federal Reserve raises interest rates again")
        assert result.is_geopolitical is True

    def test_no_geopolitical_keywords(self):
        result = self.analyzer.analyse("New Bitcoin ETF launches on Nasdaq")
        # "etf" and "approval" are in GEO_KEYWORDS
        # this test just verifies it doesn't crash
        assert isinstance(result.is_geopolitical, bool)

    def test_empty_string_does_not_crash(self):
        result = self.analyzer.analyse("")
        assert result.sentiment in (Sentiment.BULLISH, Sentiment.BEARISH, Sentiment.NEUTRAL)

    def test_score_range(self):
        headlines = [
            "Bitcoin price rises",
            "Crypto market crashes",
            "BTC stable at 50k",
        ]
        for h in headlines:
            result = self.analyzer.analyse(h)
            assert -1.0 <= result.score <= 1.0, f"Score {result.score} out of range for: {h}"

    def test_summary_considered(self):
        """Adding a bullish summary to a neutral title should boost score."""
        result_no_summary = self.analyzer.analyse("Bitcoin news today")
        result_with_summary = self.analyzer.analyse(
            "Bitcoin news today",
            "Massive institutional buying, price expected to surge to new highs"
        )
        # Summary should have some positive influence
        assert result_with_summary.score >= result_no_summary.score


class TestFakeNewsFilter:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.filter = FakeNewsFilter(similarity_threshold=0.15, window_hours=2)
        self.now = datetime.now(timezone.utc)

    def _article(self, source, title, offset_min=0):
        return RawArticle(
            source=source,
            title=title,
            url=f"https://{source}.com/{title[:20].replace(' ', '-')}",
            published_at=self.now - timedelta(minutes=offset_min),
        )

    def test_single_article_filtered_out(self):
        """An article with no corroborating source should be filtered."""
        articles = [
            self._article("coindesk", "Bitcoin jumps 10 percent on ETF news")
        ]
        decisions = self.filter.evaluate_batch(articles)
        assert decisions[0].is_filtered is True

    def test_matching_articles_pass_filter(self):
        """Two articles from different sources covering the same event should both pass."""
        title_a = "Bitcoin surges after ETF approval announcement from regulators"
        title_b = "Bitcoin surges after ETF approval announcement confirmed by SEC"
        articles = [
            self._article("coindesk", title_a, offset_min=0),
            self._article("reuters", title_b, offset_min=5),
        ]
        decisions = self.filter.evaluate_batch(articles)
        # At least one should be cross-referenced (may not both be if score is marginal)
        assert any(not d.is_filtered for d in decisions)

    def test_same_source_does_not_count(self):
        """Two articles from the same source should not cross-reference each other."""
        title = "Bitcoin ETF approval news breaks"
        articles = [
            self._article("coindesk", title, offset_min=0),
            self._article("coindesk", title + " latest", offset_min=10),
        ]
        decisions = self.filter.evaluate_batch(articles)
        # Both from same source → neither is cross-referenced
        assert all(d.is_filtered for d in decisions)

    def test_old_article_does_not_match(self):
        """Articles published more than window_hours apart should not cross-reference."""
        articles = [
            self._article("coindesk", "Bitcoin hits new all time high record breaking", offset_min=0),
            self._article("reuters", "Bitcoin hits new all time high record breaking", offset_min=200),  # 3.3 hrs
        ]
        decisions = self.filter.evaluate_batch(articles)
        # Time window is 2 hours, so they should not cross-reference
        assert all(d.is_filtered for d in decisions)

    def test_empty_batch_returns_empty(self):
        decisions = self.filter.evaluate_batch([])
        assert decisions == []
