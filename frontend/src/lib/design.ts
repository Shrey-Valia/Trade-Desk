import { colors as paletteColors } from "./palette";

/**
 * Runtime color export. Components import named tokens (e.g. `colors.bullish`,
 * `colors.fgPrimary`) for inline SVG fills and stroke colors. Class-based
 * color application (`text-fg-primary`, `bg-tier-1`, `border-amber`) is
 * preferred for HTML elements; this export exists for the cases where a
 * runtime hex string is required. See DESIGN.md for the full token spec.
 */
export const colors = paletteColors as Readonly<typeof paletteColors>;
