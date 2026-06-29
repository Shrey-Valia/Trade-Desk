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
  // WS6 a11y: fgTertiary lifted #83837A → #9A9A90 so it clears AA (≥4.5:1)
  // even on the lifted tier-2 / tier-3 surfaces where it was ~3.85:1 (a fail
  // for normal-size text). It is used as real label/placeholder text in 300+
  // spots, so it must meet the normal-text bar, not just AA-large.
  fgPrimary: "#E8E8E0",
  fgSecondary: "#C4C4BC",
  fgTertiary2: "#9B9B92",
  fgTertiary: "#9A9A90",
  fgDisabled: "#3F3F3A",

  // Borders — bumped up so they read against the lifted background.
  borderHairline: "#2F3545",
  borderStrong: "#3A4258",

  // Price semantics — reserved for +/- price moves + P&L coloring.
  // WS6 a11y: bearish lifted #E85C5C → #F06A6A. As text it sat at ~4.29:1 on
  // tier-2 (an AA fail for normal text); the lift clears AA-large everywhere
  // and AA on the tier-0/1/2 surfaces where most P&L text renders. (Candle
  // bearish is a SEPARATE, user-tunable token in userSettings — unchanged.)
  bullish: "#4DD17C",
  bearish: "#F06A6A",

  // Accents.
  accentAmber: "#F0A030", // ACTIVE / SELECTED only.
  accentCyan: "#4FB8C8",  // neutral / quiet annotation accent.
  // WS6 a11y: warning lifted #C97A3A → #D98A4A to clear AA (≥4.5:1) on the
  // lifted tiers (was ~4.44 on tier-2).
  warning: "#D98A4A",     // alerts / "market closed" notices.

  // User position highlight (entry triangle + breakeven lines).
  // WS6 a11y: lifted #D946EF → #E673F5 to clear AA as text + 3:1 as a graphic.
  positionMagenta: "#E673F5",

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
