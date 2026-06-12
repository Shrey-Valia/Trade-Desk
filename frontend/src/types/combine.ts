import { z } from "zod";

export const CombineOutSchema = z.object({
  id: z.number().int(),
  name: z.string(),
  tier: z.string(),
  account_code: z.string(),
  status: z.string(),
  starting_balance: z.number(),
  realized_pnl: z.number(),
  balance: z.number(),
  hwm: z.number(),
  mll: z.number(),
  dll_used: z.number(),
  dll_budget: z.number(),
  /** Display-only objective — no enforcement. */
  profit_target: z.number(),
  /** realized/target clamped to [0,1]. */
  objective_progress: z.number(),
  created_at: z.string(),
});
export type CombineOut = z.infer<typeof CombineOutSchema>;

export const CombinesOutSchema = z.object({
  combines: z.array(CombineOutSchema),
  active_combine_id: z.number().int().nullable(),
  slots_used: z.number().int(),
  slots_total: z.number().int(),
});
export type CombinesOut = z.infer<typeof CombinesOutSchema>;

export interface PurchaseInput {
  tier: "50K" | "100K" | "150K";
  name?: string;
}
