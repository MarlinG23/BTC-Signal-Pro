/**
 * History category — signal outcomes and alert log.
 */

import { useLiveData } from "../context/LiveDataContext";
import { SignalHistory } from "../components/SignalHistory";
import { AlertLog } from "../components/AlertLog";

export function HistoryPage() {
  const { historicalSignals, signalsLoading, allAlerts } = useLiveData();

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <div className="lg:col-span-2">
        <SignalHistory
          signals={historicalSignals ?? []}
          loading={signalsLoading}
        />
      </div>
      <div>
        <AlertLog alerts={allAlerts} />
      </div>
    </div>
  );
}
