import { z } from "zod";

export const McProbabilityLevelSchema = z.object({
  label: z.string(),
  level: z.number(),
  prob_touch: z.number(),
  prob_close_above: z.number(),
});

export const McResponseSchema = z.object({
  symbol: z.string(),
  horizon_days: z.number(),
  n_paths: z.number(),
  sigma: z.number(),
  spot: z.number(),
  mean_close: z.number(),
  std_close: z.number(),
  ci_95: z.tuple([z.number(), z.number()]),
  sample_paths: z.array(z.array(z.number())),
  bands: z.record(z.array(z.number())),
  probabilities: z.array(McProbabilityLevelSchema),
});

export type McResponse = z.infer<typeof McResponseSchema>;
export type McProbabilityLevel = z.infer<typeof McProbabilityLevelSchema>;
