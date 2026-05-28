/**
 * Single source of truth for the dashboard color palette.
 *
 * Both `lib/design.ts` (TS API used at runtime) and `tailwind.config.js`
 * (build-time Tailwind theme) import from this file.
 *
 * This file is the runtime palette; `DESIGN.md` at the project root is the
 * authoritative design system contract. Bloomberg Terminal archetype —
 * graphite-black surface, amber + cyan accents. Bullish/bearish are
 * reserved for price semantics only.
 *
 * The Trade-Desk redesign adds three intermediate grayscale stops and a
 * dedicated warning color. AMBER means exactly one thing — "active /
 * selected RIGHT NOW." Errors are bearish-red. Warnings are the new
 * warning hex.
 */
export const colors = {
  // Surface elevation tiers
  bgTier0: "#0A0C12",
  bgTier1: "#0E1118",
  bgTier2: "#11141C",
  bgTier3: "#161A24", // selected/active control fill (timeframe button etc.)

  // Foreground (text) tiers — five-stop ramp.
  //   primary    default text, values
  //   secondary  normal labels (above values) — bright enough to read at a glance
  //   tertiary2  muted labels (sub-context, axis ticks, dim sub-headers)
  //   tertiary   decorative chrome, separator hints (fails AA for body)
  //   disabled   dead controls / inactive cells
  fgPrimary: "#E8E8E0",
  fgSecondary: "#C4C4BC",
  fgTertiary2: "#8A8A82",
  fgTertiary: "#5A5A52",
  fgDisabled: "#3F3F3A",

  // Borders
  borderHairline: "#1F222A",
  borderStrong: "#2A2E38",

  // Price semantics — reserved for +/- price moves
  bullish: "#4DD17C",
  bearish: "#E85C5C",

  // Accents
  accentAmber: "#F0A030", // ACTIVE / SELECTED only.
  accentCyan: "#4FB8C8",  // neutral / quiet annotation accent.
  warning: "#C97A3A",     // muted orange-red — alerts / "market closed"
                          // notices. Distinct from amber and bearish.

  // User position highlight (entry triangle + breakeven lines). The
  // chart already uses #D946EF; surfaced here as a token.
  positionMagenta: "#D946EF",
};
