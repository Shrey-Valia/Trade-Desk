import { colors } from "./src/lib/palette.js";

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      // Single source of truth: src/lib/palette.js. All hex literals live
      // there. Commit 13 (Bloomberg revamp) stripped the legacy aliases —
      // these are the canonical tokens, and the only ones that exist.
      colors: {
        // Surface elevation
        "tier-0": colors.bgTier0,
        "tier-1": colors.bgTier1,
        "tier-2": colors.bgTier2,
        "tier-3": colors.bgTier3,
        // Foreground tiers — five-stop ramp.
        fg: {
          primary: colors.fgPrimary,
          secondary: colors.fgSecondary,
          "tertiary-2": colors.fgTertiary2,
          tertiary: colors.fgTertiary,
          disabled: colors.fgDisabled,
        },
        // Borders
        hairline: colors.borderHairline,
        "hairline-strong": colors.borderStrong,
        // Semantic price
        bullish: colors.bullish,
        bearish: colors.bearish,
        // Accents — amber = ACTIVE/SELECTED, cyan = quiet, warning = alert.
        amber: colors.accentAmber,
        cyan: colors.accentCyan,
        warning: colors.warning,
        // User position highlight (entry triangle, BE lines).
        position: colors.positionMagenta,
        // Action affordance (BUY / SELL filled buttons).
        "action-buy": colors.actionBuy,
        "action-buy-hover": colors.actionBuyHover,
        "action-buy-active": colors.actionBuyActive,
        "action-sell": colors.actionSell,
        "action-sell-hover": colors.actionSellHover,
        "action-sell-active": colors.actionSellActive,
      },
      fontFamily: {
        // IBM Plex Mono only. `sans` aliased to mono so default body font
        // and any `font-sans` usage resolve identically; `mono` is the
        // canonical name. No proportional stack — DESIGN.md mandates one
        // typeface across the dashboard.
        sans: ['"IBM Plex Mono"', "ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      fontSize: {
        // Readability revamp: the floor was raised so nothing legible renders
        // below 11px (was 9px) and the top of the ramp gives real hierarchy
        // (display 22, large 18). Token NAMES are unchanged so existing usages
        // keep working; only the pixel values moved up. tiny/xs2 are the label
        // tier, body the reading tier, medium/large/display the value+heading
        // tiers. Hard rule: no inline fontSize below 11px anywhere.
        tiny: ["11px", "15px"], // smallest LABEL size (uppercase chips, captions)
        xs2: ["12px", "16px"], // secondary labels / dense table text
        sm: ["13px", "18px"],
        body: ["13px", "18px"], // default reading size
        medium: ["15px", "21px"], // emphasized values
        large: ["18px", "24px"], // sub-headings / hero values
        display: ["22px", "28px"], // page + panel headings
      },
      borderRadius: {
        hair: "2px",
        // Visual rework: 4px radius for the Topstep-style filled
        // buttons. Hairline panels keep 0; only buttons opt into 4px.
        btn: "4px",
      },
      spacing: {
        // Semantic density scale (additive to Tailwind's default spacing) so
        // breathing room is a deliberate token choice, not an ad-hoc value.
        // Use these for panel/section/card rhythm; defaults still apply.
        cell: "4px",
        "cell-x": "6px",
        section: "8px",
        group: "12px",
        region: "16px",
        page: "24px",
      },
      letterSpacing: {
        // Uppercase labels per DESIGN.md type spec.
        "label-up": "0.08em",
      },
      keyframes: {
        // Toast entrance: slide down + fade. Exit is handled by unmount
        // (the store removes the node); a fade-in alone reads cleanly.
        "toast-enter": {
          from: { opacity: "0", transform: "translateY(-8px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        // The global reduced-motion rule in index.css clamps duration, so
        // this respects prefers-reduced-motion automatically.
        "toast-enter": "toast-enter 180ms ease-out",
      },
    },
  },
  plugins: [],
};
