import { z } from "zod";

export const BsPointSchema = z.object({
  price: z.number(),
  pnl: z.number(),
});

export const BsGreeksSchema = z.object({
  delta: z.number(),
  gamma: z.number(),
  theta: z.number(),
  vega: z.number(),
});

export const BsResponseSchema = z.object({
  payoff_at_expiry: z.array(BsPointSchema),
  current_value: z.array(BsPointSchema),
  cost_debit_credit: z.number(),
  max_gain: z.number().nullable(),
  max_loss: z.number().nullable(),
  unlimited_gain: z.boolean(),
  unlimited_loss: z.boolean(),
  edge_pnl_low: z.number(),
  edge_pnl_high: z.number(),
  breakevens: z.array(z.number()),
  greeks: BsGreeksSchema,
  prob_profit: z.number().nullable(),
});

export type BsResponse = z.infer<typeof BsResponseSchema>;
export type BsPoint = z.infer<typeof BsPointSchema>;
export type BsGreeks = z.infer<typeof BsGreeksSchema>;

export const STRATEGY_TYPES = [
  // Order matters — Long Straddle is the visual default per Phase 5 spec.
  { value: "long_straddle",     label: "Long Straddle (ATM)" },
  { value: "long_call",         label: "Long Call" },
  { value: "long_put",          label: "Long Put" },
  { value: "short_call",        label: "Short Call" },
  { value: "short_put",         label: "Short Put" },
  { value: "bull_call_spread",  label: "Bull Call Spread" },
  { value: "bear_put_spread",   label: "Bear Put Spread" },
  { value: "bull_put_spread",   label: "Bull Put Spread (credit)" },
  { value: "bear_call_spread",  label: "Bear Call Spread (credit)" },
  { value: "long_strangle",     label: "Long Strangle" },
  { value: "iron_condor",       label: "Iron Condor" },
  { value: "calendar_spread",   label: "Calendar Spread" },
] as const;

export type StrategyType = (typeof STRATEGY_TYPES)[number]["value"];
