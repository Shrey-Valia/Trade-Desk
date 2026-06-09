import { z } from "zod";

/** One trimmed news item from GET /api/news. Mirrors the backend
 *  NewsItem model; `summary` may be an empty string. */
export const NewsItemSchema = z.object({
  id: z.string(),
  headline: z.string(),
  summary: z.string(),
  source: z.string(),
  url: z.string(),
  created_at: z.string(),
});

export const NewsResponseSchema = z.object({
  symbol: z.string(),
  items: z.array(NewsItemSchema),
});

export type NewsItem = z.infer<typeof NewsItemSchema>;
export type NewsResponse = z.infer<typeof NewsResponseSchema>;
