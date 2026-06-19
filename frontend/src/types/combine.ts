import { z } from "zod";

export const CombineOutSchema = z.object({
  id: z.number().int(),
  name: z.string(),
  tier: z.string(),
  account_code: z.string(),
  /** Lifecycle: active | archived. */
  status: z.string(),
  /** Settlement outcome: active | passed | failed (permanent). */
  outcome: z.enum(["active", "passed", "failed"]).default("active"),
  starting_balance: z.number(),
  realized_pnl: z.number(),
  balance: z.number(),
  hwm: z.number(),
  /** Settled HWM — basis of the fixed-intraday MLL floor. */
  settled_hwm: z.number().default(0),
  mll: z.number(),
  dll_used: z.number(),
  dll_budget: z.number(),
  /** DLL hit today → day-locked (lifts at the 5pm-PT settlement). */
  day_locked: z.boolean().default(false),
  /** Realized profit needed to PASS (6% of starting balance). */
  profit_target: z.number(),
  /** realized/target clamped to [0,1]. */
  objective_progress: z.number(),
  /** Scaling-plan cap: max contracts per position at the current built equity. */
  max_contracts: z.number().int().default(1),
  /** True once the eval passed (auto-funded). */
  funded: z.boolean().default(false),
  /** ISO timestamp the account was funded, or null. */
  funded_at: z.string().nullable().default(null),
  /** Available payout: trader's split of profit, net of prior requests
   *  (0 until the funded account is activated). */
  payout_eligible: z.number().default(0),
  /** Lifetime payout already requested on this account. */
  payout_requested: z.number().default(0),
  /** Pricing path: "activation" | "no_activation". */
  pricing_path: z.string().default("activation"),
  /** Trader's profit share once funded (0.80 or 0.50). */
  profit_split: z.number().default(0.8),
  /** Monthly subscription paid for this combine. */
  monthly_price: z.number().default(0),
  /** Funded but not yet activated — payouts locked until the fee is paid. */
  activation_required: z.boolean().default(false),
  /** Activation fee owed to unlock payouts ($149 on the activation path). */
  activation_fee: z.number().default(0),
  /** True once the funded account is activated (payouts unlocked). */
  funded_activated: z.boolean().default(false),
  /** Copy trading: this combine mirrors the lead combine's trades. */
  copy_follow: z.boolean().default(false),
  /** Size multiplier applied to the lead's contracts before clamping. */
  copy_multiplier: z.number().default(1),
  created_at: z.string(),
});
export type CombineOut = z.infer<typeof CombineOutSchema>;

export const CombineEventSchema = z.object({
  id: z.number().int(),
  combine_id: z.number().int(),
  combine_name: z.string().nullable(),
  /** funded | failed | settled | reset | payout */
  type: z.string(),
  message: z.string(),
  amount: z.number().nullable(),
  created_at: z.string(),
});
export type CombineEvent = z.infer<typeof CombineEventSchema>;

export const PayoutOutSchema = z.object({
  combine_id: z.number().int(),
  amount: z.number(),
  requested_at: z.string(),
});
export type PayoutOut = z.infer<typeof PayoutOutSchema>;

export const CombinesOutSchema = z.object({
  combines: z.array(CombineOutSchema),
  active_combine_id: z.number().int().nullable(),
  slots_used: z.number().int(),
  slots_total: z.number().int(),
  /** Copy-trading lead combine (null = copy trading off). */
  copy_lead_combine_id: z.number().int().nullable().default(null),
});
export type CombinesOut = z.infer<typeof CombinesOutSchema>;

export interface CopyFollowerInput {
  combine_id: number;
  multiplier: number;
}

export interface CopyConfigInput {
  lead_combine_id: number | null;
  followers: CopyFollowerInput[];
}

export interface PurchaseInput {
  tier: "50K" | "100K" | "150K";
  name?: string;
  /** Pricing path chosen on the buy screen (default activation). */
  pricing_path?: "activation" | "no_activation";
  /** Profit-split choice (default 80/20). */
  split?: "80_20" | "50_50";
}
