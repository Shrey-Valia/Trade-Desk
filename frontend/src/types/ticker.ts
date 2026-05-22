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
});

export type TickerDetail = z.infer<typeof TickerDetailSchema>;
