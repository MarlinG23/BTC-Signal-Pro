/**
 * Research category — backtester and operational status.
 */

import { BacktestPanel } from "../components/BacktestPanel";
import { StatusBar } from "../components/StatusBar";

export function ResearchPage() {
  return (
    <div className="space-y-4">
      <StatusBar />
      <BacktestPanel />
    </div>
  );
}
