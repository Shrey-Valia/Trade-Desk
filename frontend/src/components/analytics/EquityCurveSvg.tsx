import { colors } from "@/lib/design";
import type { EquityPoint } from "@/types/analytics";

interface Props {
  points: EquityPoint[];
  /** ISO dates bounding the largest peak-to-trough window, for shading. */
  drawdownPeakDate?: string | null;
  drawdownTroughDate?: string | null;
  /**
   * Opt-in BALANCE mode (dashboard). When set, the curve leads with this
   * value (the combine's starting balance) instead of a synthetic 0, the
   * y-axis reads as absolute $ balance, and the MLL / Profit-Target
   * reference lines are drawn. Omitted on the Analytics page, where the
   * chart stays in cumulative-P&L mode (leads with 0, signed axis).
   */
  baseline?: number;
  /** Maximum-loss-limit floor — drawn as a reference line (balance mode). */
  mll?: number;
  /** Profit-target balance level — drawn as a reference line (balance mode). */
  profitTarget?: number;
}

/**
 * Equity curve — cumulative realized P&L (Analytics) or account balance
 * over time (Dashboard), drawn as an SVG to match the design kit: area
 * fill colored by the final sign, round-level gridlines + right-axis
 * labels, and the largest-drawdown window shaded. In balance mode it also
 * overlays the MLL floor and Profit-Target lines, Topstep-style.
 */
export function EquityCurveSvg({
  points,
  drawdownPeakDate,
  drawdownTroughDate,
  baseline,
  mll,
  profitTarget,
}: Props) {
  if (points.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-tiny text-fg-tertiary">
        No closed trades yet — equity curve appears once trades close.
      </div>
    );
  }

  const balanceMode = baseline != null;

  const W = 1000;
  const H = 220;
  const padT = 14;
  const padB = 22;
  const padL = 6;
  const padR = 64;

  // Lead with the baseline (balance mode) or a synthetic 0 (P&L mode) so
  // the curve starts at the right place.
  const lead = baseline ?? 0;
  const pts = [lead, ...points.map((p) => p.cumulative_pnl)];
  // Reference levels are only meaningful in balance mode; fold them into
  // the range so the lines always fit on the axis.
  const refs = balanceMode
    ? [mll, profitTarget].filter((v): v is number => v != null)
    : [];
  // P&L mode anchors the range at 0 (so break-even is always visible);
  // balance mode lets the data + reference lines define it.
  const anchors = balanceMode ? [] : [0];
  const hi = Math.max(...pts, ...refs, ...anchors);
  const lo = Math.min(...pts, ...refs, ...anchors);
  const span = hi - lo || 1;

  const x = (i: number) => padL + (i / (pts.length - 1)) * (W - padL - padR);
  const y = (v: number) => padT + (1 - (v - lo) / span) * (H - padT - padB);

  const line = pts.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(" ");
  const last = pts[pts.length - 1];
  const up = balanceMode ? last >= lead : last >= 0;
  const col = up ? colors.bullish : colors.bearish;
  // Area fills down to the zero line (P&L) or the chart floor (balance).
  const fillBaseY = balanceMode ? y(lo) : y(0);
  const area = `${line} L ${x(pts.length - 1).toFixed(1)} ${fillBaseY.toFixed(1)} L ${x(0).toFixed(1)} ${fillBaseY.toFixed(1)} Z`;

  // Round-level gridlines.
  const step = span > 4000 ? 1000 : span > 1500 ? 500 : span > 600 ? 250 : 100;
  const grid: number[] = [];
  for (let g = Math.ceil(lo / step) * step; g <= hi; g += step) grid.push(g);

  const fmtAxis = (v: number) =>
    balanceMode
      ? `$${Math.round(v).toLocaleString()}`
      : `${v > 0 ? "+" : v < 0 ? "−" : ""}$${Math.abs(v)}`;

  // Drawdown band: map the peak/trough dates to x. Points share dates, so
  // take the first index at/after the peak for the peak, last matching for
  // the trough. Dates index into `points`, which sit at pts index j+1.
  const peakJ = drawdownPeakDate ? points.findIndex((p) => p.date === drawdownPeakDate) : -1;
  const troughJ = drawdownTroughDate
    ? points.map((p) => p.date).lastIndexOf(drawdownTroughDate)
    : -1;
  const showBand = peakJ >= 0 && troughJ >= 0 && troughJ > peakJ;

  const refLine = (value: number, color: string, label: string) => {
    const yy = y(value);
    return (
      <g>
        <line
          x1={padL}
          y1={yy}
          x2={W - padR}
          y2={yy}
          stroke={color}
          strokeWidth="1"
          strokeDasharray="4 3"
          vectorEffect="non-scaling-stroke"
          opacity={0.8}
        />
        <text
          x={W - padR + 6}
          y={yy + 3}
          fill={color}
          fontSize="10"
          fontFamily='"IBM Plex Mono", ui-monospace, monospace'
        >
          {label}
        </text>
      </g>
    );
  };

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
            opacity={!balanceMode && g === 0 ? 0.9 : 0.4}
          />
          <text
            x={W - padR + 6}
            y={y(g) + 3}
            fill={colors.fgTertiary}
            fontSize="10"
            fontFamily='"IBM Plex Mono", ui-monospace, monospace'
          >
            {fmtAxis(g)}
          </text>
        </g>
      ))}
      <path d={area} fill={col} opacity="0.1" />
      <path d={line} fill="none" stroke={col} strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
      {balanceMode && mll != null && refLine(mll, colors.bearish, "MLL")}
      {balanceMode && profitTarget != null && refLine(profitTarget, colors.bullish, "TARGET")}
      <circle cx={x(pts.length - 1)} cy={y(last)} r="3" fill={col} />
    </svg>
  );
}
