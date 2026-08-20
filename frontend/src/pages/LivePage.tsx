/**
 * Live category — current signal, higher-timeframe gates, confluence.
 */

import { useLiveData } from "../context/LiveDataContext";
import { SignalBadge } from "../components/SignalBadge";
import { TrendPanel } from "../components/TrendPanel";
import { MtfConfluencePanel } from "../components/MtfConfluencePanel";
import { FearGreedGauge } from "../components/FearGreedGauge";

export function LivePage() {
  const {
    indicators,
    snap4h,
    snap4hLoading,
    displaySignal,
    displayWait,
    trend4h,
    livePrice,
    fearGreed,
  } = useLiveData();

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <div className="lg:col-span-2 space-y-4">
        <SignalBadge
          signal={displaySignal}
          waitSignal={displayWait}
          trend4h={trend4h}
          currentPrice={livePrice}
          atr14={indicators?.atr_14 ?? null}
          fearGreed={fearGreed?.value ?? null}
        />
        <TrendPanel
          snapshot1m={indicators}
          snapshot4h={snap4h}
          loading={snap4hLoading}
        />
        <MtfConfluencePanel />
      </div>
      <div className="space-y-4">
        <FearGreedGauge data={fearGreed} compact />
      </div>
    </div>
  );
}
