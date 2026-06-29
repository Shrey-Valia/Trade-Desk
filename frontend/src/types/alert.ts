import { z } from "zod";

/** Alert kinds (WS6) — price crossing, earnings window, or order fill. */
export const AlertKindSchema = z.enum(["price", "earnings", "fill"]);
export type AlertKind = z.infer<typeof AlertKindSchema>;

export const AlertDirectionSchema = z.enum(["above", "below"]);
export type AlertDirection = z.infer<typeof AlertDirectionSchema>;

export const AlertSchema = z.object({
  id: z.number(),
  kind: AlertKindSchema,
  symbol: z.string(),
  threshold: z.number().nullable(),
  direction: AlertDirectionSchema.nullable(),
  status: z.enum(["active", "triggered"]),
  note: z.string(),
  created_at: z.string(),
  triggered_at: z.string().nullable(),
});
export type Alert = z.infer<typeof AlertSchema>;

export const AlertsResponseSchema = z.object({ alerts: z.array(AlertSchema) });
export type AlertsResponse = z.infer<typeof AlertsResponseSchema>;

export const EvaluateResponseSchema = z.object({
  triggered: z.array(AlertSchema),
});
export type EvaluateResponse = z.infer<typeof EvaluateResponseSchema>;

export interface AlertInput {
  kind: AlertKind;
  symbol: string;
  threshold?: number | null;
  direction?: AlertDirection | null;
  note?: string;
}
