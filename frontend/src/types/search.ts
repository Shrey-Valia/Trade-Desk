import { z } from "zod";

export const SearchHitSchema = z.object({
  symbol: z.string(),
  name: z.string(),
  has_0dte_today: z.boolean(),
});
export type SearchHit = z.infer<typeof SearchHitSchema>;

export const TickerSearchResponseSchema = z.object({
  query: z.string(),
  results: z.array(SearchHitSchema),
});
export type TickerSearchResponse = z.infer<typeof TickerSearchResponseSchema>;

// New (Phase 1 curated rework): stars + popular slate.
export const StarsResponseSchema = z.object({
  symbols: z.array(z.string()),
});
export type StarsResponse = z.infer<typeof StarsResponseSchema>;

export const PopularEntrySchema = z.object({
  symbol: z.string(),
  name: z.string(),
  has_0dte_today: z.boolean(),
});
export type PopularEntry = z.infer<typeof PopularEntrySchema>;

export const PopularResponseSchema = z.object({
  results: z.array(PopularEntrySchema),
});
export type PopularResponse = z.infer<typeof PopularResponseSchema>;
