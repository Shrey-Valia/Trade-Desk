import { colors } from "@/lib/design";

interface Props {
  label: string;
  /** Center text (the real number, e.g. "100%" or "$380"). */
  value: string;
  /** Optional sub-label under the gauge. */
  sub?: string;
  /** Arc fill 0–1, or null for "no data" (renders an empty track + "—"). */
  fraction: number | null;
  /** Arc + value color (hex from @/lib/design). */
  color: string;
}

/**
 * Topstep-style 270° arc gauge. The arc fill is `fraction` of the sweep;
 * the center shows the real value (the fraction is the visual, the number
 * is the truth). Pure SVG — no chart lib. Scales to its container width.
 */
export function GaugeDial({ label, value, sub, fraction, color }: Props) {
  const SIZE = 100;
  const STROKE = 9;
  const r = (SIZE - STROKE) / 2 - 2;
  const cx = SIZE / 2;
  const cy = SIZE / 2;
  const circ = 2 * Math.PI * r;
  const ARC = 0.75; // 270° sweep, gap at the bottom
  const track = ARC * circ;
  const f = fraction == null ? 0 : Math.max(0, Math.min(1, fraction));
  const filled = f * track;

  return (
    <div className="flex flex-col items-center gap-1">
      <div className="relative w-full" style={{ maxWidth: 108 }}>
        <svg viewBox={`0 0 ${SIZE} ${SIZE}`} width="100%" style={{ display: "block" }}>
          {/* Rotate so the 270° arc is centered at the top with the gap at
              the bottom (start at 135°). */}
          <g transform={`rotate(135 ${cx} ${cy})`}>
            <circle
              cx={cx}
              cy={cy}
              r={r}
              fill="none"
              stroke={colors.borderHairline}
              strokeWidth={STROKE}
              strokeDasharray={`${track} ${circ}`}
              strokeLinecap="round"
            />
            {fraction != null && (
              <circle
                cx={cx}
                cy={cy}
                r={r}
                fill="none"
                stroke={color}
                strokeWidth={STROKE}
                strokeDasharray={`${filled} ${circ}`}
                strokeLinecap="round"
              />
            )}
          </g>
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span
            className="text-medium font-medium tabular-nums"
            style={{ color: fraction == null ? colors.fgTertiary : color }}
          >
            {fraction == null ? "—" : value}
          </span>
        </div>
      </div>
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2 text-center"
        style={{ fontSize: 9 }}
      >
        {label}
      </span>
      {sub && <span className="text-tiny text-fg-tertiary-2 tabular-nums">{sub}</span>}
    </div>
  );
}
