import { colors } from "@/lib/design";

interface Props {
  /** Square size in px. Defaults to 36 — the left-rail size. */
  size?: number;
  /** Optional title for accessibility (rendered as <title>). */
  title?: string;
}

/**
 * Trade Desk mark — softly-squared amber badge with a "TD" monogram.
 *
 *   ┌──────────────┐
 *   │              │
 *   │     T D      │
 *   │              │
 *   └──────────────┘
 *
 * Outer: rounded-square outline, 2px amber stroke, transparent fill
 * so the rail's bg-tier-1 shows through. Corner radius is 5/36 of
 * the outer size so the badge scales proportionally — softly squared,
 * not pillowy.
 *
 * Inside: "TD" in IBM Plex Mono 500 weight, fg-primary, slight
 * negative letter-spacing so the T and D sit close. Sized to fill
 * ~62% of the badge's interior height (font-size ≈ 0.55 × outer size,
 * with the badge's 2px border subtracting a couple px on each axis).
 *
 * Colors come from the palette token export (no hardcoded hex), so a
 * future palette swap in Settings propagates here automatically.
 */
export function TradeDeskMark({ size = 36, title = "Trade Desk" }: Props) {
  // Geometry proportional to size so the mark scales cleanly from
  // 16px (favicon) to 64px+ (splash). The 36px viewBox keeps the
  // numbers concrete and easy to reason about.
  const viewBox = 36;
  const radius = 5; // ~14% — soft square corner
  const stroke = 2;
  const fontSize = 20; // ~62% of inner height after the 2px border
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox={`0 0 ${viewBox} ${viewBox}`}
      width={size}
      height={size}
      role="img"
      aria-label={title}
    >
      <title>{title}</title>
      <rect
        x={stroke / 2}
        y={stroke / 2}
        width={viewBox - stroke}
        height={viewBox - stroke}
        rx={radius}
        ry={radius}
        fill="none"
        stroke={colors.accentAmber}
        strokeWidth={stroke}
      />
      <text
        x={viewBox / 2}
        y={viewBox / 2}
        textAnchor="middle"
        dominantBaseline="central"
        fontFamily='"IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace'
        fontSize={fontSize}
        fontWeight={500}
        letterSpacing="-0.02em"
        fill={colors.fgPrimary}
      >
        TD
      </text>
    </svg>
  );
}
