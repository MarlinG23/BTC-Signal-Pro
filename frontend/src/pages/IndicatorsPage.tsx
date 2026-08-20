/**
 * Indicators category — full 1-minute technical snapshot.
 */

import { useLiveData } from "../context/LiveDataContext";
import { IndicatorsPanel } from "../components/IndicatorsPanel";

export function IndicatorsPage() {
  const { indicators } = useLiveData();

  return (
    <div className="max-w-3xl">
      <IndicatorsPanel snapshot={indicators} />
    </div>
  );
}
