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
        // Bloomberg ramp — pixel values match DESIGN.md. Some legacy names
        // (tiny=9, xs2=11, sm=13) coexist with canonical aliases (body=13,
        // medium=15, large=17, display=19) where pixel values overlap. Both
        // sets are in active use across the codebase post-revamp; renaming
        // is a separate refactor that doesn't change render output.
        tiny: ["9px", "12px"],
        xs2: ["11px", "14px"],
        sm: ["13px", "17px"],
        body: ["13px", "18px"],
        medium: ["15px", "20px"],
        large: ["17px", "22px"],
        display: ["19px", "24px"],
      },
      borderRadius: {
        // Bloomberg caps at 2px. Tailwind's default `rounded-none` and
        // `rounded-sm` (2px) cover everything; only `rounded-hair` is
        // exposed as a named convenience.
        hair: "2px",
      },
      letterSpacing: {
        // Uppercase labels per DESIGN.md type spec.
        "label-up": "0.08em",
      },
    },
  },
  plugins: [],
};
