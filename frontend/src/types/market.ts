import { z } from "zod";

export const MarketStatusSchema = z.object({
  status: z.enum(["open", "closed", "pre", "after"]),
  label: z.string(),
  next_open: z.string().nullable(),
  next_close: z.string().nullable(),
});

const IndexQuoteSchema = z.object({
  symbol: z.string(),
  price: z.number(),
  change_pct: z.number(),
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
