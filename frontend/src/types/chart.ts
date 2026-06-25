import { z } from "zod";

export const BarPointSchema = z.object({
  t: z.string(),
  o: z.number(),
  h: z.number(),
  l: z.number(),
  c: z.number(),
  v: z.number(),
});

export const WallLevelSchema = z.object({
  strike: z.number(),
  oi: z.number(),
});

export const ChartAnnotationsSchema = z.object({
  expected_move_upper: z.number().nullable(),
  expected_move_lower: z.number().nullable(),
  call_wall: WallLevelSchema.nullable(),
  put_wall: WallLevelSchema.nullable(),
  max_pain: z.number().nullable(),
  gamma_flip: z.number().nullable(),
  earnings_date: z.string().nullable(),
  // WS-B: auto support/resistance from swing structure. Default [] so an
  // older /bars envelope (no S/R fields) still parses.
  support_levels: z.array(z.number()).default([]),
  resistance_levels: z.array(z.number()).default([]),
});

export const ChartResponseSchema = z.object({
  symbol: z.string(),
  timeframe: z.string(),
  bars: z.array(BarPointSchema),
  annotations: ChartAnnotationsSchema,
  oi_source: z.string(),
});

export type ChartResponse = z.infer<typeof ChartResponseSchema>;
export type ChartAnnotations = z.infer<typeof ChartAnnotationsSchema>;
export type BarPoint = z.infer<typeof BarPointSchema>;
export type WallLevel = z.infer<typeof WallLevelSchema>;
/**
 * Standard TradingView/Topstep timeframe ladder. The value IS the
 * candle interval — backend's _TIMEFRAME_CONFIG owns the matching
 * lookback window and Alpaca TimeFrame mapping. Default selection
 * (cold open + Settings picker default): "5m".
 */
export type ChartTimeframe = "1m" | "5m" | "15m" | "1h" | "4h" | "1D";

export const CHART_TIMEFRAMES: readonly ChartTimeframe[] = [
  "1m",
  "5m",
  "15m",
  "1h",
  "4h",
  "1D",
] as const;

export const DEFAULT_CHART_TIMEFRAME: ChartTimeframe = "5m";

/** True when the value is one of the currently-supported timeframes.
 *  Useful for narrowing a persisted-localStorage value back into the
 *  union after a ladder change. */
export function isChartTimeframe(v: unknown): v is ChartTimeframe {
  return (
    typeof v === "string" &&
    (CHART_TIMEFRAMES as readonly string[]).includes(v)
  );
}
