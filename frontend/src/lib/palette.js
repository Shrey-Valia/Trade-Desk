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
  // Surface elevation tiers — NEUTRAL charcoal (was dark navy). Not pure black,
  // no blue tint: a gray-black ground so the brighter money colors read as
  // electric without eye strain.
  bgTier0: "#16181C",
  bgTier1: "#1D2026",
  bgTier2: "#24272F",
  bgTier3: "#2C3038",

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
  // Lifted #9B9B92/#9A9A90 → #ABABA2 so the smallest labels read a touch
  // brighter (~7:1 on #16181C) while staying clearly below fgSecondary.
  fgTertiary2: "#ABABA2",
  fgTertiary: "#ABABA2",
  fgDisabled: "#3F3F3A",

  // Borders — neutral charcoal steps (drop the blue tint).
  borderHairline: "#2B2F37",
  borderStrong: "#3A3F49",

  // Price semantics — BRIGHTER money colors. These are the +/- price moves and
  // P&L: they should feel electric against the charcoal ground. (Candle bullish/
  // bearish is a SEPARATE, user-tunable token in userSettings — unchanged.)
  bullish: "#22E584", // bright mint-green — winning P&L, up moves
  bearish: "#FF5A6A", // bright red — losing P&L, down moves

  // Accents. MONOCHROME — no accent color. The UI chrome is black & white:
  // the "amber" token (active / selected state + indicator/EM chart lines) is
  // now WHITE, and the neutral-marker token is a mid GRAY. The name `accentAmber`
  // is kept for token stability (Tailwind `*-amber` classes + ~300 call sites);
  // only the value changed. The ONLY colors that remain are the money semantics
  // (bullish/bearish + BUY/SELL) and the rare risk-warning amber — a trader must
  // read profit/loss and "approaching your limit" at a glance.
  accentAmber: "#FFFFFF", // (white) active/selected UI + indicator/EM lines
  accentCyan: "#808690",  // neutral / quiet annotation accent (mid gray)
  warning: "#E8C84A",     // rare risk advisory (approaching MLL/DLL) — kept

  // User position highlight (entry triangle + breakeven lines) — pure white,
  // the brightest thing on the chart because it's YOUR position.
  positionMagenta: "#FFFFFF",

  // Action affordance colors — BUY / SELL filled buttons. BRIGHT now (the
  // product should feel alive, not muted). Dark text sits on these vivid fills.
  actionBuy: "#1FC463",
  actionBuyHover: "#2BDE74",
  actionBuyActive: "#18A452",
  actionSell: "#F03B4E",
  actionSellHover: "#FF5063",
  actionSellActive: "#CE2C3E",
};
