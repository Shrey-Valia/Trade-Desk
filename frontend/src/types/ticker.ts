import { z } from "zod";

export const TickerDetailSchema = z.object({
  symbol: z.string(),
  price: z.number(),
  change_dollar: z.number(),
  change_pct: z.number(),
  day_high: z.number(),
  day_low: z.number(),
  fifty_two_week_high: z.number(),
  fifty_two_week_low: z.number(),
  volume: z.number(),
  avg_volume_20d: z.number(),
  next_earnings_date: z.string().nullable(),
  days_to_earnings: z.number().nullable(),
  // Freshness metadata. nullable().optional() so the UI works both before
  // and after the backend starts sending them; served_stale = the feed
  // stalled and this is the last good snapshot.
  as_of: z.string().nullable().optional(),
  served_stale: z.boolean().nullable().optional(),
});

export type TickerDetail = z.infer<typeof TickerDetailSchema>;
