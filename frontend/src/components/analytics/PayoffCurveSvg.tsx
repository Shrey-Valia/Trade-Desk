import { colors } from "@/lib/design";

interface Props {
  prices: number[];
  payoffExpiration: number[];
  payoffToday: number[];
  breakevens: number[];
  spot: number;
}

/**
 * Option P&L payoff diagram (Webull-style): underlying price on x, dollar
 * P&L on y. Expiration curve solid + two-tone shaded (profit green / loss
 * red), the theta-decayed "today" curve dashed, a zero baseline, the
 * current spot marker, and break-even verticals. Pure SVG, matching the
 * EquityCurveSvg conventions.
 */
export function PayoffCurveSvg({
  prices,
  payoffExpiration,
  payoffToday,
  breakevens,
  spot,
}: Props) {
  if (prices.length < 2) {
    return (
      <div className="flex items-center justify-center h-full text-tiny text-fg-tertiary">
        No payoff data.
      </div>
    );
  }

  const W = 420;
  const H = 150;
  const padT = 14;
  const padB = 16;
  const padL = 6;
  const padR = 52;

  const xMin = prices[0];
  const xMax = prices[prices.length - 1];
  const ys = [...payoffExpiration, ...payoffToday, 0];
  const yHi = Math.max(...ys);
  const yLo = Math.min(...ys);
  const ySpan = yHi - yLo || 1;

  const x = (p: number) => padL + ((p - xMin) / (xMax - xMin || 1)) * (W - padL - padR);
  const y = (v: number) => padT + (1 - (v - yLo) / ySpan) * (H - padT - padB);

  const path = (vals: number[]) =>
    vals
      .map((v, i) => `${i ? "L" : "M"}${x(prices[i]).toFixed(1)} ${y(v).toFixed(1)}`)
      .join(" ");

  // Two-tone fill: clamp the expiration curve to ≥0 (profit) and ≤0 (loss)
  // and fill each back to the zero line. Clamping at the samples keeps it
  // generic across calls / puts / straddles without per-structure logic.
  const zeroY = y(0);
  const areaTo = (clamp: (v: number) => number, fill: string) => {
    const top = payoffExpiration
      .map((v, i) => `${i ? "L" : "M"}${x(prices[i]).toFixed(1)} ${y(clamp(v)).toFixed(1)}`)
      .join(" ");
    return (
      <path
        d={`${top} L ${x(xMax).toFixed(1)} ${zeroY.toFixed(1)} L ${x(xMin).toFixed(1)} ${zeroY.toFixed(1)} Z`}
        fill={fill}
        opacity={0.12}
      />
    );
  };

  const fmtY = (v: number) =>
    `${v > 0 ? "+" : v < 0 ? "−" : ""}$${Math.abs(Math.round(v)).toLocaleString()}`;

  return (
    <svg
      width="100%"
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      style={{ display: "block", height: "100%" }}
      role="img"
      aria-label="Option position payoff diagram"
    >
      {areaTo((v) => Math.max(v, 0), colors.bullish)}
      {areaTo((v) => Math.min(v, 0), colors.bearish)}

      {/* Zero P&L baseline + label */}
      <line
        x1={padL}
        y1={zeroY}
        x2={W - padR}
        y2={zeroY}
        stroke={colors.borderHairline}
        strokeWidth="1"
        vectorEffect="non-scaling-stroke"
        opacity={0.9}
      />
      <text
        x={W - padR + 6}
        y={zeroY + 3}
        fill={colors.fgTertiary}
        fontSize="9"
        fontFamily='"IBM Plex Mono", ui-monospace, monospace'
      >
        $0
      </text>
      {/* y extent labels */}
      <text
        x={W - padR + 6}
        y={y(yHi) + 7}
        fill={colors.fgTertiary}
        fontSize="9"
        fontFamily='"IBM Plex Mono", ui-monospace, monospace'
      >
        {fmtY(yHi)}
      </text>
      <text
        x={W - padR + 6}
        y={y(yLo) - 2}
        fill={colors.fgTertiary}
        fontSize="9"
        fontFamily='"IBM Plex Mono", ui-monospace, monospace'
      >
        {fmtY(yLo)}
      </text>

      {/* Break-even verticals */}
      {breakevens.map((be) => (
        <g key={be}>
          <line
            x1={x(be)}
            y1={padT}
            x2={x(be)}
            y2={H - padB}
            stroke={colors.fgTertiary}
            strokeWidth="1"
            strokeDasharray="3 3"
            vectorEffect="non-scaling-stroke"
            opacity={0.7}
          />
          <text
            x={x(be)}
            y={H - padB + 12}
            fill={colors.fgTertiary}
            fontSize="9"
            textAnchor="middle"
            fontFamily='"IBM Plex Mono", ui-monospace, monospace'
          >
            {be.toFixed(0)}
          </text>
        </g>
      ))}

      {/* Current spot marker */}
      <line
        x1={x(spot)}
        y1={padT}
        x2={x(spot)}
        y2={H - padB}
        stroke={colors.accentAmber}
        strokeWidth="1"
        vectorEffect="non-scaling-stroke"
        opacity={0.8}
      />

      {/* Theta-decayed "today" curve (dashed) + expiration curve (solid) */}
      <path
        d={path(payoffToday)}
        fill="none"
        stroke={colors.fgTertiary}
        strokeWidth="1.2"
        strokeDasharray="4 3"
        vectorEffect="non-scaling-stroke"
      />
      <path
        d={path(payoffExpiration)}
        fill="none"
        stroke={colors.fgPrimary}
        strokeWidth="1.6"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
