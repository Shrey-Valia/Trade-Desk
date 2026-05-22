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
 * Phase 1 introduced legacy aliases for migration; commit 13 strips them.
 * Every component now consumes these canonical tokens directly.
 */
export const colors = {
  // Surface elevation tiers
  bgTier0: "#0A0C12",
  bgTier1: "#0E1118",
  bgTier2: "#11141C",

  // Foreground (text) tiers
  fgPrimary: "#E8E8E0",
  fgSecondary: "#8A8A82",
  fgTertiary: "#5A5A52", // decorative only — fails AA for body text

  // Borders
  borderHairline: "#1F222A",
  borderStrong: "#2A2E38",

  // Price semantics — reserved for +/- price moves
  bullish: "#4DD17C",
  bearish: "#E85C5C",

  // Accents
  accentAmber: "#F0A030",
  accentCyan: "#4FB8C8",
};
