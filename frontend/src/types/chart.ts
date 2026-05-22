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
export type ChartTimeframe = "1D" | "5D" | "1M" | "3M";
