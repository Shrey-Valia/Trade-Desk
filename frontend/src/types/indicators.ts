import { z } from "zod";

/**
 * Technical-indicator overlay payload from
 * GET /api/ticker/{symbol}/indicators.
 *
 * `series[*].values` is aligned 1:1 with `times` (and with the chart's
 * bar array, since both come off the same backend bars). Warm-up bars
 * are `null` so the chart can plot a LineSeries against the same
 * timestamps with no index juggling.
 *
 * `pane` routes the series in AnnotatedChart:
 *   - "price": shares the main price scale (SMA / EMA / VWAP)
 *   - "oscillator": its own 0–100 pane (RSI)
 *   - "volatility": its own absolute-value pane (ATR)
 */
export const IndicatorSeriesSchema = z.object({
  key: z.string(),
  label: z.string(),
  pane: z.string(),
  values: z.array(z.number().nullable()),
});

export const IndicatorsResponseSchema = z.object({
  symbol: z.string(),
  timeframe: z.string(),
  times: z.array(z.string()),
  series: z.array(IndicatorSeriesSchema),
});

export type IndicatorSeries = z.infer<typeof IndicatorSeriesSchema>;
export type IndicatorsResponse = z.infer<typeof IndicatorsResponseSchema>;

/**
 * The toggleable indicator catalog the UI exposes. The `key` IS the
 * backend query token (window size encoded in the key); `color` is a
 * design-token hex chosen so the price-pane overlays don't collide with
 * the magenta POSITION line or the candle bullish/bearish hues.
 *
 * Colors are filled in by the toolbar/chart from lib/design tokens — see
 * INDICATOR_COLORS in AnnotatedChart so the single source of truth for
 * the hex lives next to the chart that draws it.
 */
export interface IndicatorDef {
  key: string;
  label: string;
  pane: "price" | "oscillator" | "volatility";
}

export const INDICATOR_CATALOG: readonly IndicatorDef[] = [
  { key: "sma20", label: "SMA 20", pane: "price" },
  { key: "ema50", label: "EMA 50", pane: "price" },
  { key: "vwap", label: "VWAP", pane: "price" },
  { key: "rsi14", label: "RSI 14", pane: "oscillator" },
  { key: "atr14", label: "ATR 14", pane: "volatility" },
] as const;
