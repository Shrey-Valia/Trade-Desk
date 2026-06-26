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
 * The toggleable indicator catalog the UI exposes. `key` is the indicator
 * FAMILY token (sma / ema / vwap / rsi / atr) — the backend query token is
 * built per-request as `family:period` from the periods store, so one
 * catalog entry covers every period the trader picks for that family.
 *
 * `parameterizable` families expose a small numeric period input on their
 * toolbar chip; `defaultPeriod` is the seed (and the value used when no
 * override is stored). VWAP is cumulative — no window, no period input.
 *
 * Colors are filled in by the toolbar/chart from lib/design tokens — see
 * INDICATOR_COLORS in AnnotatedChart so the single source of truth for
 * the hex lives next to the chart that draws it.
 */
export interface IndicatorDef {
  /** Family token — the stable identity (sma/ema/vwap/rsi/atr). */
  key: string;
  /** Short label shown on the chip; the period (if any) is appended live. */
  label: string;
  pane: "price" | "oscillator" | "volatility";
  /** Whether the trader can tune the lookback window for this family. */
  parameterizable: boolean;
  /** Seed period; null for windowless families (VWAP). */
  defaultPeriod: number | null;
}

export const INDICATOR_CATALOG: readonly IndicatorDef[] = [
  { key: "sma", label: "SMA", pane: "price", parameterizable: true, defaultPeriod: 20 },
  { key: "ema", label: "EMA", pane: "price", parameterizable: true, defaultPeriod: 50 },
  { key: "vwap", label: "VWAP", pane: "price", parameterizable: false, defaultPeriod: null },
  { key: "rsi", label: "RSI", pane: "oscillator", parameterizable: true, defaultPeriod: 14 },
  { key: "atr", label: "ATR", pane: "volatility", parameterizable: true, defaultPeriod: 14 },
] as const;

/** Period clamp — mirrors the backend's [2, 400] bound so the UI can't
 *  send a window the server will silently clamp. */
export const MIN_INDICATOR_PERIOD = 2;
export const MAX_INDICATOR_PERIOD = 400;

/** A catalog entry by family key (or undefined). */
export function indicatorDef(key: string): IndicatorDef | undefined {
  return INDICATOR_CATALOG.find((d) => d.key === key);
}
