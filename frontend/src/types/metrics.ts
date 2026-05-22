import { z } from "zod";

export const MetricsResponseSchema = z.object({
  iv_rank: z.number().nullable(),
  iv_rank_status: z.string().nullable(),
  vrp: z.number().nullable(),
  skew_25d: z.number().nullable(),
  pc_ratio: z.number().nullable(),
  max_pain: z.number().nullable(),
});

export type MetricsResponse = z.infer<typeof MetricsResponseSchema>;
