import { colors } from "@/lib/design";

interface Props {
  /** Square size in px. Defaults to 36 — the left-rail size. */
  size?: number;
  /** Base color. Defaults to fg-primary. */
  color?: string;
  /** Amber accent (the breakeven line). Defaults to accent-amber. */
  accent?: string;
  /** Optional title for accessibility (rendered as <title>). */
  title?: string;
}

/**
 * Trade Desk mark — an abstract candle-with-breakeven monogram that
 * doubles as a "TD" silhouette.
 *
 * The geometry:
 *   - A vertical wick (the "T" stem) anchored on a square base block.
 *   - A bullish candle body fills the top half of the base.
 *   - A horizontal accent line (amber, slightly off-center toward the
 *     wick) crosses the base — this is the "breakeven" reference, the
 *     thing the rest of the product is built around. The line also
 *     reads as the cross-bar of the "T".
 *   - A small offset stub at the lower-right forms the "D" terminator
 *     (a single pixel-rounded notch). Restrained, geometric, no
 *     decorative flourish.
 *
 * Single foreground color (fg-primary by default) plus one amber
 * accent, monochromatic otherwise. Sized for a 36px rail slot but
 * scales cleanly down to 16px or up to 64px.
 */
export function TradeDeskMark({
  size = 36,
  color = colors.fgPrimary,
  accent = colors.accentAmber,
  title = "Trade Desk",
}: Props) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 32 32"
      width={size}
      height={size}
      role="img"
      aria-label={title}
    >
      <title>{title}</title>
      {/* Outer square frame — thin 1.5px stroke, no fill. Gives the
          mark its "TD" silhouette boundary. */}
      <rect
        x="3"
        y="3"
        width="26"
        height="26"
        fill="none"
        stroke={color}
        strokeWidth="1.5"
      />
      {/* Vertical wick + the upper candle body. The wick anchors at
          the bottom (y=27) and extends through the top of the candle
          body (y=8) into a small high-wick (y=5). */}
      <line
        x1="16"
        y1="5"
        x2="16"
        y2="27"
        stroke={color}
        strokeWidth="1.5"
      />
      <rect x="13" y="10" width="6" height="11" fill={color} />
      {/* Amber breakeven line — crosses horizontally at the mid, with
          a 2px stroke and a 6px endcap rounding. Reads as the bar of
          the "T" and the product's signature axis at once. */}
      <line
        x1="6"
        y1="16"
        x2="26"
        y2="16"
        stroke={accent}
        strokeWidth="2"
        strokeLinecap="round"
      />
      {/* "D" terminator — a small notch on the lower-right that
          reads as the bowl of the "D" without recreating a literal D.
          1.5px stroke, no fill. */}
      <path
        d="M22 22 Q24 22 24 24 Q24 26 22 26"
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}
