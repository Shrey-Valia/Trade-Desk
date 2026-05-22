import { colors } from "@/lib/design";

type LogoSize = "compact" | "full";

interface Props {
  size?: LogoSize;
  /** Hide the subtle cursor blink — useful for static contexts (PDF
   *  export, app icon previews) where motion isn't appropriate. The
   *  global prefers-reduced-motion media query disables it for users
   *  who opt out of motion. */
  noBlink?: boolean;
}

/**
 * Trade Desk wordmark.
 *
 *   [ TRADE DESK█ ]
 *
 * Two-weight / two-tone typography matching the watchlist's
 * ticker-over-subtitle pattern: "TRADE" weight 500 FG PRIMARY,
 * "DESK" weight 400 FG SECONDARY. Amber square brackets frame the
 * pair; the small amber rectangle before the closing bracket is the
 * terminal cursor — the signature mark, sized to cap-height with a
 * subtle ~1.2s blink (skipped under prefers-reduced-motion).
 *
 * Two sizes:
 *   compact — 14px text, fits the 36px Trade Desk toolbar
 *   full    — 22px text + 11px uppercase tagline below
 */
export function TradeDeskLogo({ size = "compact", noBlink }: Props) {
  const config =
    size === "compact"
      ? {
          fontSize: 14,
          cursorH: 11,
          cursorW: 7,
          tracking: "0.18em",
          bracketGap: 4,
          wordGap: 6,
        }
      : {
          fontSize: 22,
          cursorH: 17,
          cursorW: 10,
          tracking: "0.22em",
          bracketGap: 6,
          wordGap: 10,
        };

  const Line = (
    <span
      className="inline-flex items-baseline font-mono select-none"
      style={{ fontSize: config.fontSize, letterSpacing: config.tracking }}
      aria-label="Trade Desk"
    >
      <span style={{ color: colors.accentAmber, marginRight: config.bracketGap }}>[</span>
      <span style={{ fontWeight: 500, color: colors.fgPrimary }}>TRADE</span>
      <span style={{ width: config.wordGap, display: "inline-block" }} aria-hidden />
      <span style={{ fontWeight: 400, color: colors.fgSecondary }}>DESK</span>
      <span style={{ width: config.wordGap, display: "inline-block" }} aria-hidden />
      <span
        aria-hidden
        className={noBlink ? undefined : "td-cursor-blink"}
        style={{
          display: "inline-block",
          width: config.cursorW,
          height: config.cursorH,
          background: colors.accentAmber,
          verticalAlign: "baseline",
          // Nudge the block down so its bottom aligns with the text baseline
          // (otherwise it floats above and looks like a top-corner accent).
          transform: "translateY(2px)",
        }}
      />
      <span style={{ color: colors.accentAmber, marginLeft: config.bracketGap }}>]</span>
    </span>
  );

  if (size === "compact") return Line;

  return (
    <span className="inline-flex flex-col gap-1 select-none" aria-label="Trade Desk">
      {Line}
      <span
        className="text-tiny uppercase tracking-label-up text-fg-tertiary"
        style={{ letterSpacing: "0.18em" }}
      >
        Options · Futures · Terminal
      </span>
    </span>
  );
}
