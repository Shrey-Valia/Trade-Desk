import { z } from "zod";

export const WatchlistMetadataSchema = z.object({
  news_count: z.number().nullish(),
  earnings_date: z.string().nullish(),
  iv30_percentile: z.number().nullish(),
  options_volume_ratio: z.number().nullish(),
  sentiment_score: z.number().nullish(),
});

export const WatchlistItemSchema = z.object({
  symbol: z.string(),
  price: z.number(),
  change_pct: z.number(),
  subtitle: z.string(),
  metadata: WatchlistMetadataSchema.default({}),
});

export const WatchlistResponseSchema = z.object({
  hot_now: z.array(WatchlistItemSchema),
  earnings: z.array(WatchlistItemSchema),
  unusual_options: z.array(WatchlistItemSchema),
  sentiment_up: z.array(WatchlistItemSchema),
  sentiment_down: z.array(WatchlistItemSchema),
  notes: z.record(z.string()).default({}),
  updated_at: z.string(),
});

export type WatchlistItem = z.infer<typeof WatchlistItemSchema>;
export type WatchlistResponse = z.infer<typeof WatchlistResponseSchema>;
export type WatchlistCategoryKey =
  | "hot_now"
  | "earnings"
  | "unusual_options"
  | "sentiment_up"
  | "sentiment_down";
