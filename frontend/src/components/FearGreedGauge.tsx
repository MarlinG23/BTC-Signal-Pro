/**
 * Fear & Greed Index gauge displayed as a semi-circular arc meter.
 * Color transitions from red (extreme fear) to green (extreme greed).
 */

import clsx from "clsx";
import { FearGreedData } from "../utils/types";
import { timeAgoMinutes } from "../utils/format";

interface FearGreedGaugeProps {
  data: FearGreedData | null;
}

function getColor(value: number): string {
  if (value <= 20) return "#ff3b5c";      // Extreme Fear
  if (value <= 40) return "#ff8c42";      // Fear
  if (value <= 60) return "#ffd700";      // Neutral
  if (value <= 80) return "#7ed957";      // Greed
  return "#00ff88";                        // Extreme Greed
}

function getArcPath(value: number): string {
  // SVG arc from 180° to 0° (left to right), covering the range 0–100
  const cx = 60;
  const cy = 60;
  const r = 50;
  const startAngle = 180;
  const endAngle = 180 - (value / 100) * 180;

  const toRad = (deg: number) => (deg * Math.PI) / 180;
  const x1 = cx + r * Math.cos(toRad(startAngle));
  const y1 = cy - r * Math.sin(toRad(startAngle));
  const x2 = cx + r * Math.cos(toRad(endAngle));
  const y2 = cy - r * Math.sin(toRad(endAngle));

  const largeArc = value > 50 ? 1 : 0;
  return `M ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2}`;
}

export function FearGreedGauge({ data }: FearGreedGaugeProps) {
  return (
    <div className="card">
      <h2 className="text-sm font-semibold text-brand-muted uppercase tracking-wider mb-4">
        Fear & Greed Index
      </h2>

      {data ? (
        <div className="flex flex-col items-center">
          {/* SVG Gauge */}
          <svg viewBox="0 0 120 70" className="w-40 h-24">
            {/* Background track */}
            <path
              d="M 10 60 A 50 50 0 0 1 110 60"
              fill="none"
              stroke="#1e1e2e"
              strokeWidth="10"
              strokeLinecap="round"
            />
            {/* Value arc */}
            <path
              d={getArcPath(data.value)}
              fill="none"
              stroke={getColor(data.value)}
              strokeWidth="10"
              strokeLinecap="round"
            />
            {/* Center value */}
            <text
              x="60"
              y="58"
              textAnchor="middle"
              fontSize="18"
              fontWeight="bold"
              fill={getColor(data.value)}
            >
              {data.value}
            </text>
          </svg>

          <p
            className={clsx("text-lg font-bold mt-1")}
            style={{ color: getColor(data.value) }}
          >
            {data.classification}
          </p>
          <p className="text-brand-muted text-xs mt-1">
            Updated {timeAgoMinutes(data.updated_at ?? data.timestamp)}
          </p>

          {/* Scale labels */}
          <div className="flex justify-between w-full mt-3 text-xs text-brand-muted">
            <span className="text-red-400">Extreme Fear</span>
            <span className="text-yellow-400">Neutral</span>
            <span className="text-emerald-400">Extreme Greed</span>
          </div>
        </div>
      ) : (
        <div className="flex items-center justify-center py-6 text-brand-muted text-sm">
          Loading…
        </div>
      )}
    </div>
  );
}
