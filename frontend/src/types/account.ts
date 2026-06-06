import { z } from "zod";

export const TIER_KEYS = ["50K", "100K", "150K"] as const;
export type TierKey = (typeof TIER_KEYS)[number];

export const TierSpecSchema = z.object({
  key: z.string(),
  label: z.string(),
  starting_balance: z.number(),
  trailing_distance: z.number(),
  initial_mll: z.number(),
  /** Daily Loss Limit budget — resets at the start of each ET trading day. */
  dll_amount: z.number(),
});
export type TierSpec = z.infer<typeof TierSpecSchema>;

export const AccountStateSchema = z.object({
  active_tier: z.string(),
  starting_balance: z.number(),
  /** Sum of realized P&L from closed trades on the active tier. */
  realized_pnl: z.number(),
  /** starting_balance + realized_pnl. Unrealized is added client-side. */
  balance: z.number(),
  high_water_mark: z.number(),
  mll: z.number(),
  /**
   * Realized-only DLL signal — today's realized losses on the active
   * tier, clamped to ≥0. Frontend folds in any active-position UPL at
   * display time, mirroring the BAL pattern.
   */
  dll_used: z.number(),
  dll_budget: z.number(),
  dll_breached: z.boolean(),
  tiers: z.array(TierSpecSchema),
});
export type AccountState = z.infer<typeof AccountStateSchema>;
