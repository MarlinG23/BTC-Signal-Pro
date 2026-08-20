/**
 * News category — Fear & Greed and headline sentiment.
 */

import { useLiveData } from "../context/LiveDataContext";
import { FearGreedGauge } from "../components/FearGreedGauge";
import { NewsFeed } from "../components/NewsFeed";

export function NewsPage() {
  const { fearGreed, allNews, newsLoading } = useLiveData();

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <div className="lg:col-span-2">
        <NewsFeed
          items={allNews}
          loading={newsLoading && allNews.length === 0}
        />
      </div>
      <div>
        <FearGreedGauge data={fearGreed} />
      </div>
    </div>
  );
}
