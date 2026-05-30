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
