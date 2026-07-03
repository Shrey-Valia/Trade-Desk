import { z } from "zod";

export const MarketStatusSchema = z.object({
  status: z.enum(["open", "closed", "pre", "after"]),
  label: z.string(),
  next_open: z.string().nullable(),
  next_close: z.string().nullable(),
  // Early-close surfacing (half days). nullable().optional() so the UI works
  // both before and after the backend starts sending them.
  today_close: z.string().nullable().optional(),
  is_early_close: z.boolean().nullable().optional(),
});

const IndexQuoteSchema = z.object({
  symbol: z.string(),
  price: z.number(),
  change_pct: z.number(),
  // True when the value is a prior-session close (VIX comes from FRED's
  // end-of-day series) — the UI labels it instead of faking a live delta.
  prev_close_only: z.boolean().nullable().optional(),
  as_of: z.string().nullable().optional(),
});

export const IndicesResponseSchema = z.object({
  spy: IndexQuoteSchema.nullable(),
  qqq: IndexQuoteSchema.nullable(),
  vix: IndexQuoteSchema.nullable(),
});

export const LiquidUniverseSchema = z.object({
  symbols: z.array(z.string()),
});

export type MarketStatus = z.infer<typeof MarketStatusSchema>;
export type IndicesResponse = z.infer<typeof IndicesResponseSchema>;
export type IndexQuote = z.infer<typeof IndexQuoteSchema>;
export type LiquidUniverse = z.infer<typeof LiquidUniverseSchema>;
