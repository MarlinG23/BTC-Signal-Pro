/**
 * News feed component showing verified articles with sentiment labels.
 */

import clsx from "clsx";
import { ExternalLink, Globe, AlertTriangle } from "lucide-react";
import { NewsItem, Sentiment } from "../utils/types";
import { timeAgo, truncate } from "../utils/format";

interface NewsFeedProps {
  items: NewsItem[];
  loading?: boolean;
}

const SENTIMENT_STYLES: Record<
  Sentiment,
  { label: string; className: string }
> = {
  BULLISH: { label: "Bullish", className: "text-emerald-400 bg-emerald-400/10 border-emerald-400/30" },
  BEARISH: { label: "Bearish", className: "text-red-400 bg-red-400/10 border-red-400/30" },
  NEUTRAL: { label: "Neutral", className: "text-brand-muted bg-brand-muted/10 border-brand-muted/20" },
};

const SOURCE_LABELS: Record<string, string> = {
  coindesk: "CoinDesk",
  reuters: "Reuters",
  fear_greed: "Fear & Greed",
  glassnode: "Glassnode",
  coinglass: "CoinGlass",
};

function NewsCard({ item }: { item: NewsItem }) {
  const sentiment = item.sentiment
    ? SENTIMENT_STYLES[item.sentiment]
    : SENTIMENT_STYLES.NEUTRAL;

  return (
    <a
      href={item.url}
      target="_blank"
      rel="noopener noreferrer"
      className="block group hover:bg-brand-border/30 rounded-lg p-3 -mx-1 transition-colors"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          {/* Source + Time */}
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <span className="text-xs font-medium text-brand-blue bg-brand-blue/10 border border-brand-blue/20 rounded px-2 py-0.5">
              {SOURCE_LABELS[item.source] || item.source}
            </span>
            {item.sentiment && (
              <span
                className={clsx(
                  "text-xs border rounded px-2 py-0.5",
                  sentiment.className
                )}
              >
                {sentiment.label}
              </span>
            )}
            {item.is_geopolitical && (
              <span className="text-xs text-yellow-400 bg-yellow-400/10 border border-yellow-400/20 rounded px-2 py-0.5 flex items-center gap-1">
                <AlertTriangle className="w-3 h-3" />
                Macro
              </span>
            )}
          </div>

          {/* Title */}
          <p className="text-sm text-white group-hover:text-brand-blue transition-colors leading-snug">
            {truncate(item.title, 100)}
          </p>

          {/* Time */}
          <p className="text-xs text-brand-muted mt-1">
            {timeAgo(item.published_at)}
          </p>
        </div>

        <ExternalLink className="w-4 h-4 text-brand-muted group-hover:text-brand-blue transition-colors shrink-0 mt-1" />
      </div>
    </a>
  );
}

export function NewsFeed({ items, loading }: NewsFeedProps) {
  return (
    <div className="card">
      <div className="flex items-center gap-2 mb-4">
        <Globe className="w-4 h-4 text-brand-muted" />
        <h2 className="text-sm font-semibold text-brand-muted uppercase tracking-wider">
          Verified News Feed
        </h2>
        <span className="ml-auto text-xs text-brand-muted">{items.length} articles</span>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-6 text-brand-muted text-sm">
          Fetching news…
        </div>
      ) : items.length === 0 ? (
        <div className="flex items-center justify-center py-6 text-brand-muted text-sm">
          No verified articles yet
        </div>
      ) : (
        <div className="space-y-1 max-h-96 overflow-y-auto">
          {items.map((item) => (
            <NewsCard key={item.id} item={item} />
          ))}
        </div>
      )}
    </div>
  );
}
