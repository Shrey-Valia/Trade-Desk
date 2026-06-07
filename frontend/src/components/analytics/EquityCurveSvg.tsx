import { colors } from "@/lib/design";
import type { EquityPoint } from "@/types/analytics";

interface Props {
  points: EquityPoint[];
  /** ISO dates bounding the largest peak-to-trough window, for shading. */
  drawdownPeakDate?: string | null;
  drawdownTroughDate?: string | null;
}

/**
 * Equity curve — cumulative realized P&L, drawn as an SVG to match the
 * design kit (ui_kits/analytics): area fill colored by the final P&L
 * sign, round-level gridlines + right-axis labels, a zero baseline, and
 * the largest-drawdown window shaded. Replaces the lightweight-charts
 * equity chart so we can shade the DD band the library can't.
 */
export function EquityCurveSvg({ points, drawdownPeakDate, drawdownTroughDate }: Props) {
  if (points.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-tiny text-fg-tertiary">
        No closed trades yet — equity curve appears once trades close.
      </div>
    );
  }

  const W = 1000;
  const H = 220;
  const padT = 14;
  const padB = 22;
  const padL = 6;
  const padR = 56;

  // Lead with a synthetic 0 so the curve starts at break-even.
  const pts = [0, ...points.map((p) => p.cumulative_pnl)];
  const hi = Math.max(0, ...pts);
  const lo = Math.min(0, ...pts);
  const span = hi - lo || 1;

  const x = (i: number) => padL + (i / (pts.length - 1)) * (W - padL - padR);
  const y = (v: number) => padT + (1 - (v - lo) / span) * (H - padT - padB);

  const line = pts.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(" ");
  const last = pts[pts.length - 1];
  const col = last >= 0 ? colors.bullish : colors.bearish;
  const zeroY = y(0);
  const area = `${line} L ${x(pts.length - 1).toFixed(1)} ${zeroY.toFixed(1)} L ${x(0).toFixed(1)} ${zeroY.toFixed(1)} Z`;

  // Round-level gridlines.
  const step = span > 1500 ? 500 : span > 600 ? 250 : 100;
  const grid: number[] = [];
  for (let g = Math.ceil(lo / step) * step; g <= hi; g += step) grid.push(g);

  // Drawdown band: map the peak/trough dates to x. Points share dates, so
  // take the first index at/after the peak for the peak, last matching for
  // the trough. Dates index into `points`, which sit at pts index j+1.
  const peakJ = drawdownPeakDate ? points.findIndex((p) => p.date === drawdownPeakDate) : -1;
  const troughJ = drawdownTroughDate
    ? points.map((p) => p.date).lastIndexOf(drawdownTroughDate)
    : -1;
  const showBand = peakJ >= 0 && troughJ >= 0 && troughJ > peakJ;

  return (
    <svg
      width="100%"
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      style={{ display: "block", height: "100%" }}
    >
      {showBand && (
        <rect
          x={x(peakJ + 1)}
          y={padT}
          width={x(troughJ + 1) - x(peakJ + 1)}
          height={H - padT - padB}
          fill={colors.bearish}
          opacity={0.08}
        />
      )}
      {grid.map((g) => (
        <g key={g}>
          <line
            x1={padL}
            y1={y(g)}
            x2={W - padR}
            y2={y(g)}
            stroke={colors.borderHairline}
            strokeWidth="1"
            vectorEffect="non-scaling-stroke"
            opacity={g === 0 ? 0.9 : 0.4}
          />
          <text
            x={W - padR + 6}
            y={y(g) + 3}
            fill={colors.fgTertiary}
            fontSize="10"
            fontFamily='"IBM Plex Mono", ui-monospace, monospace'
          >
            {g > 0 ? "+" : g < 0 ? "−" : ""}${Math.abs(g)}
          </text>
        </g>
      ))}
      <path d={area} fill={col} opacity="0.1" />
      <path d={line} fill="none" stroke={col} strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
      <circle cx={x(pts.length - 1)} cy={y(last)} r="3" fill={col} />
    </svg>
  );
}
