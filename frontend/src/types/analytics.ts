import { z } from "zod";

export const KpiBlockSchema = z.object({
  total_trades: z.number().int(),
  open_trades: z.number().int(),
  closed_trades: z.number().int(),
  win_rate: z.number().nullable(),
  net_pnl: z.number(),
  profit_factor: z.number().nullable(),
  avg_winner: z.number().nullable(),
  avg_loser: z.number().nullable(),
  expectancy: z.number().nullable(),
  avg_r: z.number().nullable(),
  largest_winner: z.number().nullable(),
  largest_loser: z.number().nullable(),
});
export type KpiBlock = z.infer<typeof KpiBlockSchema>;

export const StrategyBucketSchema = z.object({
  strategy: z.string(),
  trades: z.number().int(),
  closed: z.number().int(),
  win_rate: z.number().nullable(),
  net_pnl: z.number(),
  avg_pnl: z.number().nullable(),
  profit_factor: z.number().nullable(),
  avg_r: z.number().nullable(),
});
export type StrategyBucket = z.infer<typeof StrategyBucketSchema>;

export const DteBucketSchema = z.object({
  label: z.string(),
  trades: z.number().int(),
  win_rate: z.number().nullable(),
  avg_pnl: z.number().nullable(),
  net_pnl: z.number(),
});
export type DteBucket = z.infer<typeof DteBucketSchema>;

export const MistakeBucketSchema = z.object({
  tag: z.string(),
  trades: z.number().int(),
  net_pnl: z.number(),
  avg_pnl: z.number().nullable(),
  total_r: z.number().nullable(),
});
export type MistakeBucket = z.infer<typeof MistakeBucketSchema>;

export const EquityPointSchema = z.object({
  date: z.string(),
  cumulative_pnl: z.number(),
});
export type EquityPoint = z.infer<typeof EquityPointSchema>;

export const EquityCurveSchema = z.object({
  points: z.array(EquityPointSchema),
  max_drawdown: z.number(),
  peak_pnl: z.number(),
  final_pnl: z.number(),
});
export type EquityCurve = z.infer<typeof EquityCurveSchema>;

export const AnalyticsFiltersSchema = z.object({
  paper: z.boolean().nullable().optional(),
  strategy: z.string().nullable().optional(),
  since: z.string().nullable().optional(),
  until: z.string().nullable().optional(),
});
export type AnalyticsFilters = z.infer<typeof AnalyticsFiltersSchema>;

export const AnalyticsResponseSchema = z.object({
  kpis: KpiBlockSchema,
  by_strategy: z.array(StrategyBucketSchema),
  by_dte: z.array(DteBucketSchema),
  by_mistake: z.array(MistakeBucketSchema),
  equity: EquityCurveSchema,
  filters: AnalyticsFiltersSchema,
});
export type AnalyticsResponse = z.infer<typeof AnalyticsResponseSchema>;
