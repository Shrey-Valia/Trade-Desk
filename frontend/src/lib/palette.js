/**
 * Single source of truth for the dashboard color palette.
 *
 * Both `lib/design.ts` (TS API used at runtime) and `tailwind.config.js`
 * (build-time Tailwind theme) import from this file.
 *
 * ── Bold rebrand (2026-07) — "Steel & Gold: the private trading desk." ──
 * The monochrome era is retired. The identity is a cool SLATE base with a
 * muted, premium GOLD accent — understated and institutional, not flashy — and
 * a disciplined five-role SEMANTIC color system where every hue means exactly
 * one thing, never decoration:
 *
 *   MONEY        bullish/bearish — P&L and price moves (desaturated to survive
 *                all-day 0DTE staring).
 *   RISK         warning(caution, an ORANGE kept distinct from the gold accent)
 *                → accentBreach — how close you are to the trailing-drawdown /
 *                daily-loss floor. accentBreach is a HOTTER red than money-loss
 *                on purpose, so "about to blow up" reads differently from
 *                "lost $40".
 *   POSITION     positionMagenta (BEAM) — YOUR position + breakeven on the
 *                price axis. The product's signature; used for NOTHING else.
 *   NAV / ACTIVE accentAmber (SIGNAL) — the one navigation accent: active tab,
 *                selected combine, active timeframe, focus, selected chain row,
 *                primary non-trade CTA fills. A muted GOLD. Token name kept as
 *                `accentAmber` for stability across ~300 `*-amber` call sites;
 *                only the value changed.
 *   QUIET        accentCyan — muted steel for low-priority annotation.
 *
 * BUY/SELL fills are a separate action-affordance axis (actionBuy/Sell).
 */
export const colors = {
  // Surface elevation tiers — deep near-black SLATE (Topstep-grade black +
  // gold). Darkened from the first slate pass toward the cinematic near-black
  // the reference prop firms use, while keeping a faint cool tint so the muted
  // gold reads as premium and the elevation steps still separate cleanly.
  bgTier0: "#0A0B0E", // near-black slate — page ground
  bgTier1: "#0F1319", // deck — panel
  bgTier2: "#161B23", // rail — raised panel / chip
  bgTier3: "#1F252F", // highest elevation

  // Foreground (text) tiers — five-stop ramp on the slate ground. fgTertiary
  // is real label/placeholder text in 300+ spots, so it clears WCAG AA on the
  // deck/rail surfaces; fgDisabled stays dim (decorative only).
  fgPrimary: "#E7EAF0",
  fgSecondary: "#99A2B2",
  fgTertiary2: "#79828F",
  fgTertiary: "#79828F",
  fgDisabled: "#3C4350",

  // Borders — cool slate hairlines.
  borderHairline: "#212734",
  borderStrong: "#333A48",

  // MONEY — desaturated so it reads clean over a full session (saturated pure
  // green/red fatigues). Candle bullish/bearish is a SEPARATE, user-tunable
  // token in userSettings — unchanged.
  bullish: "#34D39A", // spearmint — winning P&L, up moves
  bearish: "#FF5C72", // rose-red — losing P&L, down moves

  // NAV / ACTIVE accent — muted GOLD. (Token name kept as accentAmber.)
  accentAmber: "#D4A24C",
  // QUIET annotation — muted steel (low-priority marks; copy-trade role dots).
  accentCyan: "#6E7684",
  // RISK proximity — caution ORANGE (approaching the DLL / MLL buffer). Kept
  // deliberately more orange than the gold nav accent so a risk gauge never
  // reads as "active/selected".
  warning: "#F0862E",
  // RISK terminal — alarm red for BREACH / DAY-LOCK / FAILED. Deliberately
  // hotter + more saturated than `bearish` so account-death out-shouts an
  // ordinary losing trade.
  accentBreach: "#FF3B4E",

  // POSITION — the BEAM. Real magenta: the entry triangle + breakeven lines,
  // the brightest, most distinct thing on the chart because it is YOUR
  // position. Used for nothing else.
  positionMagenta: "#C264D8",

  // Action affordance — BUY / SELL filled buttons. Dark text sits on the fills.
  actionBuy: "#1FB57A",
  actionBuyHover: "#27C98A",
  actionBuyActive: "#189A67",
  actionSell: "#E24659",
  actionSellHover: "#F0576A",
  actionSellActive: "#C33547",
};
