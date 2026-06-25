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
 *   - "price": shares the main price scale (SMA / EMA / VWAP / Bollinger)
 *   - "oscillator": its own 0–100 pane (RSI / Stochastic)
 *   - "volatility": its own absolute-value pane (ATR)
 *   - "macd": MACD's own zero-centred pane (line / signal / histogram)
 *
 * `kind` tells the chart how to draw the series:
 *   - "line": a LineSeries (every overlay except below)
 *   - "histogram": a HistogramSeries (the MACD histogram)
 */
export const IndicatorSeriesSchema = z.object({
  key: z.string(),
  label: z.string(),
  pane: z.string(),
  kind: z.enum(["line", "histogram"]).default("line"),
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
  /** Backend request token sent in the `set` query param. For a
   *  multi-component indicator this is the GROUP token (`macd`/`bb`/
   *  `stoch`); the backend expands it into several component series. */
  key: string;
  label: string;
  pane: "price" | "oscillator" | "volatility" | "macd";
  /** Present on multi-component indicators (MACD / Bollinger / Stoch):
   *  the component series keys the chart will receive back, so toggling
   *  the one chip lights up all of them. Single-line indicators omit it
   *  (the chip key === the only series key). */
  componentKeys?: readonly string[];
}

export const INDICATOR_CATALOG: readonly IndicatorDef[] = [
  { key: "sma20", label: "SMA 20", pane: "price" },
  { key: "ema50", label: "EMA 50", pane: "price" },
  { key: "vwap", label: "VWAP", pane: "price" },
  {
    key: "bb",
    label: "BB",
    pane: "price",
    componentKeys: ["bb_upper", "bb_mid", "bb_lower"],
  },
  { key: "rsi14", label: "RSI 14", pane: "oscillator" },
  {
    key: "stoch",
    label: "STOCH",
    pane: "oscillator",
    componentKeys: ["stoch_k", "stoch_d"],
  },
  {
    key: "macd",
    label: "MACD",
    pane: "macd",
    componentKeys: ["macd_line", "macd_signal", "macd_hist"],
  },
  { key: "atr14", label: "ATR 14", pane: "volatility" },
] as const;
