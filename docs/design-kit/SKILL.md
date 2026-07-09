---
name: trade-desk-design
description: Use this skill to generate well-branded interfaces and assets for Trade Desk — a 0DTE options trading terminal and prop firm (Topstep for options) — either for production or throwaway prototypes/mocks. Contains essential design guidelines, colors, type, fonts, assets, and UI kit components for prototyping.
user-invocable: true
---

Read the `readme.md` file within this skill, and explore the other available files.

If creating visual artifacts (slides, mocks, throwaway prototypes, etc), copy assets out and create static HTML files for the user to view. If working on production code, you can copy assets and read the rules here to become an expert in designing with this brand.

If the user invokes this skill without any other guidance, ask them what they want to build or design, ask some questions, and act as an expert designer who outputs HTML artifacts _or_ production code, depending on the need.

## What's here
- `styles.css` — global entry point; link it to inherit every token + font.
- `tokens/` — colors, typography, spacing/radii, fonts (IBM Plex Mono).
- `assets/` — TD mark + wordmark SVGs, monoline icon set.
- `guidelines/` — foundation specimen cards (colors, type, spacing, brand).
- `components/` — React primitives (Button, MetricPill, Badge, TierPill, Stepper, PresetChips, ActionButton, ChainRow, Icon).
- `ui_kits/terminal/` — full interactive recreation of the 0DTE trading terminal.

## Non-negotiables (see readme.md for the full contract)
- Dark-navy ground (`#131722`), never pure black. IBM Plex Mono everywhere, weights 400/500 only.
- **Amber = active/selected only.** Magenta = the trader's own position only. Bullish/bearish = price & P&L only. Warning = advisories.
- 1px hairlines, radii ≤4px, no shadows / gradients / blur. Density over whitespace. Tabular numerics always on.
- Voice: direct, technical, trader-to-trader. Use `combine`, `funded`, `payout`, `MLL`, `drawdown`. Never `platform`, `solution`, `AI-powered`. No emoji.
