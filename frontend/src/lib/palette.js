/**
 * Single source of truth for the dashboard color palette.
 *
 * Both `lib/design.ts` (TS API used at runtime) and `tailwind.config.js`
 * (build-time Tailwind theme) import from this file.
 *
 * Visual rework: shifted from the prior pure-black graphite surface to
 * a softer dark-navy ground. Tier-0 lifts to #131722; three lifted
 * tiers above it. Hairlines step up too — the prior #1F222A is too
 * faint against the new ground.
 *
 * Color discipline carries forward unchanged: AMBER = active/selected
 * only. WARNING = advisories. BULLISH/BEARISH = price moves + P&L.
 * MAGENTA = user's position. The new BUY/SELL filled-button colors
 * are a distinct semantic axis (action affordance) and live as
 * `actionBuy` / `actionSell` so they don't get conflated with the
 * candle/P&L bullish/bearish hues.
 */
export const colors = {
  // Surface elevation tiers — softer dark navy, not pure black.
  bgTier0: "#131722",
  bgTier1: "#1A1F2D",
  bgTier2: "#222837",
  bgTier3: "#2A3142",

  // Foreground (text) tiers — five-stop ramp. Revamp: the two dimmest
  // CONTENT tiers were lifted so any real text clears WCAG AA on the
  // shipped #131722 ground (the old #5A5A52 tertiary was ~2.5:1 — a fail).
  // fgDisabled stays dim: it is for decorative / disabled only, never words.
  fgPrimary: "#E8E8E0",
  fgSecondary: "#C4C4BC",
  fgTertiary2: "#9B9B92",
  fgTertiary: "#83837A",
  fgDisabled: "#3F3F3A",

  // Borders — bumped up so they read against the lifted background.
  borderHairline: "#2F3545",
  borderStrong: "#3A4258",

  // Price semantics — reserved for +/- price moves + P&L coloring.
  bullish: "#4DD17C",
  bearish: "#E85C5C",

  // Accents.
  accentAmber: "#F0A030", // ACTIVE / SELECTED only.
  accentCyan: "#4FB8C8",  // neutral / quiet annotation accent.
  warning: "#C97A3A",     // alerts / "market closed" notices.

  // User position highlight (entry triangle + breakeven lines).
  positionMagenta: "#D946EF",

  // Action affordance colors — BUY / SELL filled buttons.
  // Deliberately distinct from BULLISH / BEARISH (price/P&L semantics).
  // These read as professional fills, not candy bright.
  actionBuy: "#2A8C4A",
  actionBuyHover: "#33A357",
  actionBuyActive: "#21753E",
  actionSell: "#C8434A",
  actionSellHover: "#D85258",
  actionSellActive: "#A6363C",
};
