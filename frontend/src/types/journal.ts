import { z } from "zod";

export const TradeStatusSchema = z.enum(["working", "open", "closed", "cancelled"]);
export type TradeStatus = z.infer<typeof TradeStatusSchema>;

export const OrderTypeSchema = z.enum(["market", "limit", "stop", "stop_limit"]);
export type OrderType = z.infer<typeof OrderTypeSchema>;

export const TradeLegSchema = z.object({
  side: z.enum(["call", "put"]),
  action: z.enum(["buy", "sell"]),
  strike: z.number().positive(),
  expiry: z.string(),          // ISO date
  contracts: z.number().int().positive().default(1),
  entry_price: z.number().min(0),
});
export type TradeLeg = z.infer<typeof TradeLegSchema>;

export const TradeOutSchema = z.object({
  id: z.number().int(),
  symbol: z.string(),
  strategy: z.string(),
  legs: z.array(TradeLegSchema),
  entry_date: z.string(),
  entry_underlying_price: z.number(),
  net_debit_credit: z.number(),
  status: TradeStatusSchema,
  exit_date: z.string().nullable().optional(),
  exit_underlying_price: z.number().nullable().optional(),
  realized_pnl: z.number().nullable().optional(),
  is_paper: z.boolean(),
  notes: z.string().nullable().optional(),
  /** Combine tier this trade was opened on (50K / 100K / 150K). */
  tier: z.string().default("50K"),
  /**
   * The combine instance this trade belongs to. Prefer this over `tier` for
   * scoping live terminal state to the ACTIVE combine — two combines can share
   * a tier (e.g. a copy-trade follower pair), so a tier filter would fold the
   * other combine's positions in. nullable().optional() tolerates older
   * payloads from before the backend echoed it.
   */
  combine_id: z.number().int().nullable().optional(),
  /** Accounting provenance: "execution" (moves combine equity) vs "manual". */
  origin: z.string().default("execution"),
  // Limit/stop orders + SL/TP brackets.
  order_type: OrderTypeSchema.default("market"),
  // Time-in-force for a working order ('gtc' rests; 'day' expires next session).
  time_in_force: z.enum(["day", "gtc"]).default("gtc"),
  limit_price: z.number().nullable().optional(),
  // stop_limit ENTRY: arms at stop_price, then rests as a limit at limit_price.
  stop_price: z.number().nullable().optional(),
  // Trailing stop (EXIT): trails the favorable option mark; trail_hwm is the
  // monitor-maintained high-water.
  trail_amount: z.number().nullable().optional(),
  trail_pct: z.number().nullable().optional(),
  trail_hwm: z.number().nullable().optional(),
  // OCO group id pairing sibling working orders (one fill cancels the other).
  oco_group: z.string().nullable().optional(),
  stop_loss: z.number().nullable().optional(),
  take_profit: z.number().nullable().optional(),
  // Premium-exit multiples attached at open — TP/SL trigger when the option
  // mark reaches mult × entry premium. nullable().optional(): tolerant of
  // payloads from before the backend started echoing them.
  tp_premium_mult: z.number().nullable().optional(),
  sl_premium_mult: z.number().nullable().optional(),
  // Resting close-limit on an OPEN position: signed net premium per 1×
  // structure (debit positive / credit negative). The monitor fills it AT
  // the limit when the live net mark reaches it. null = none resting.
  close_limit_price: z.number().nullable().optional(),
  close_reason: z
    .enum([
      "manual",
      "stop_loss",
      "take_profit",
      "expiry",
      "liquidation",
      "copy",
      "limit",
      "expiry_closeout",
    ])
    .nullable()
    .optional(),
  // Phase 2 metadata.
  tags: z.array(z.string()).default([]),
  mistake_tags: z.array(z.string()).default([]),
  confidence: z.number().int().min(1).max(5).nullable().optional(),
  thesis: z.string().nullable().optional(),
  planned_exit: z.string().nullable().optional(),
  risk_amount: z.number().nullable().optional(),
  screenshot_url: z.string().nullable().optional(),
  review_note: z.string().nullable().optional(),
  r_multiple: z.number().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type Trade = z.infer<typeof TradeOutSchema>;

// Portfolio-level Greek book (backend /api/journal/portfolio/greeks) —
// net exposure across every OPEN execution position on the active combine.
// delta/gamma are share-equivalents; theta/vega position dollars;
// beta_weighted_delta is SPY-share equivalents (null when SPY spot is cold).
export const PortfolioGreeksSchema = z.object({
  positions: z.number().int(),
  net: z.object({
    delta: z.number(),
    gamma: z.number(),
    theta: z.number(),
    vega: z.number(),
  }),
  beta_weighted_delta: z.number().nullable(),
  spy_spot: z.number().nullable(),
  by_symbol: z.array(
    z.object({
      symbol: z.string(),
      beta: z.number(),
      spot: z.number(),
      delta: z.number(),
      gamma: z.number(),
      theta: z.number(),
      vega: z.number(),
      beta_weighted_delta: z.number().nullable(),
    }),
  ),
});
export type PortfolioGreeks = z.infer<typeof PortfolioGreeksSchema>;

// Mirror of MISTAKE_TAG_VOCABULARY in backend schemas/journal.py — used
// as autocomplete suggestions in the close-position UI. Custom strings
// are also accepted.
export const MISTAKE_TAG_VOCABULARY: readonly string[] = [
  "chased IV crush",
  "rolled too soon",
  "no exit plan",
  "oversized",
  "revenge trade",
  "ignored regime",
  "held too long",
  "cut winner early",
] as const;

export const TradesResponseSchema = z.object({
  trades: z.array(TradeOutSchema),
});
export type TradesResponse = z.infer<typeof TradesResponseSchema>;

/** True when the trade's nearest-leg expiry is today (local). Mirrors
 * the backend's _trade_is_zerodte detection — the chart uses this to
 * decide whether to flip useTradeAnalytics into intraday mode. */
export function isZeroDteTrade(trade: Trade | null | undefined): boolean {
  if (!trade || !trade.legs?.length) return false;
  const today = new Date().toISOString().slice(0, 10); // YYYY-MM-DD local-ish
  return trade.legs.some((leg) => leg.expiry === today);
}

// Phase 2 — position analytics for the on-chart breakeven + payoff panel.
export const AnalyticsGreeksSchema = z.object({
  delta: z.number(),
  gamma: z.number(),
  theta: z.number(),
  vega: z.number(),
});

export const TradeAnalyticsSchema = z.object({
  trade_id: z.number().int(),
  symbol: z.string(),
  spot: z.number(),
  rate: z.number(),
  current_dte_days: z.number().int(),
  scrubber_dte_days: z.number().int(),
  iv_used: z.number(),
  iv_source: z.enum(["implied_from_entry", "fallback", "default"]),
  prices: z.array(z.number()),
  payoff_expiration: z.array(z.number()),
  payoff_today: z.array(z.number()),
  breakevens_expiration: z.array(z.number()),
  breakevens_today: z.array(z.number()),
  entry_underlying_price: z.number(),
  entry_date: z.string(),
  cost_basis: z.number(),
  current_value: z.number(),
  unrealized_pnl: z.number(),
  // Simulated commission, $ per side for this position. Default keeps the
  // schema tolerant of older payloads.
  commission: z.number().default(0),
  max_profit: z.number().nullable(),
  max_loss: z.number().nullable(),
  unlimited_gain: z.boolean(),
  unlimited_loss: z.boolean(),
  greeks: AnalyticsGreeksSchema,
});
export type TradeAnalytics = z.infer<typeof TradeAnalyticsSchema>;

// Mirror of EXPECTED_LEG_COUNT in backend schemas/journal.py — used to
// scaffold leg inputs in the entry form. Kept here so the form can pre-
// fill leg rows without a round-trip to the backend.
export const EXPECTED_LEG_COUNT: Record<string, number> = {
  long_call: 1,
  long_put: 1,
  short_call: 1,
  short_put: 1,
  long_straddle: 2,
  long_strangle: 2,
  bull_call_spread: 2,
  bear_put_spread: 2,
  bull_put_spread: 2,
  bear_call_spread: 2,
  calendar_spread: 2,
  iron_condor: 4,
};

// Default leg template per strategy — gives the entry form sensible
// defaults so the user only fills strikes/expiries/prices. Mirrors
// build_legs() in backend calculations/strategies.py (sides + actions
// only; strikes are user-entered relative to the chosen ATM strike).
type LegTemplate = Pick<TradeLeg, "side" | "action">;

export const STRATEGY_LEG_TEMPLATES: Record<string, LegTemplate[]> = {
  long_call: [{ side: "call", action: "buy" }],
  long_put: [{ side: "put", action: "buy" }],
  short_call: [{ side: "call", action: "sell" }],
  short_put: [{ side: "put", action: "sell" }],
  long_straddle: [
    { side: "call", action: "buy" },
    { side: "put", action: "buy" },
  ],
  long_strangle: [
    { side: "call", action: "buy" },
    { side: "put", action: "buy" },
  ],
  bull_call_spread: [
    { side: "call", action: "buy" },
    { side: "call", action: "sell" },
  ],
  bear_put_spread: [
    { side: "put", action: "buy" },
    { side: "put", action: "sell" },
  ],
  bull_put_spread: [
    { side: "put", action: "sell" },
    { side: "put", action: "buy" },
  ],
  bear_call_spread: [
    { side: "call", action: "sell" },
    { side: "call", action: "buy" },
  ],
  calendar_spread: [
    { side: "call", action: "sell" },
    { side: "call", action: "buy" },
  ],
  iron_condor: [
    { side: "call", action: "sell" },
    { side: "call", action: "buy" },
    { side: "put", action: "sell" },
    { side: "put", action: "buy" },
  ],
};

export const STRATEGY_LABELS: Record<string, string> = {
  long_call: "Long call",
  long_put: "Long put",
  short_call: "Short call",
  short_put: "Short put",
  long_straddle: "Long straddle",
  short_straddle: "Short straddle",
  long_strangle: "Long strangle",
  bull_call_spread: "Bull call spread",
  bear_put_spread: "Bear put spread",
  bull_put_spread: "Bull put spread",
  bear_call_spread: "Bear call spread",
  calendar_spread: "Calendar spread",
  iron_condor: "Iron condor",
};

export interface TradeInput {
  symbol: string;
  strategy: string;
  legs: TradeLeg[];
  entry_date: string;
  entry_underlying_price: number;
  net_debit_credit?: number | null;
  is_paper: boolean;
  notes?: string | null;
  tags?: string[];
  confidence?: number | null;
  thesis?: string | null;
  planned_exit?: string | null;
  risk_amount?: number | null;
  screenshot_url?: string | null;
}

/** PATCH /api/journal/trades/{id}/order — modify a WORKING order in place.
 *  Only the provided fields change; the backend 409s when the order is no
 *  longer working (filled/cancelled while the form was open). */
export interface WorkingOrderPatch {
  limit_price?: number;
  stop_price?: number;
  time_in_force?: "day" | "gtc";
}

export interface TradeUpdateInput {
  status?: TradeStatus;
  exit_date?: string;
  exit_underlying_price?: number;
  realized_pnl?: number;
  notes?: string;
  tags?: string[];
  mistake_tags?: string[];
  review_note?: string;
}

/** Pure helper mirroring backend compute_net_debit_credit so the form
 *  can preview the net as the user edits. */
export function computeNet(legs: TradeLeg[]): number {
  let total = 0;
  for (const leg of legs) {
    const sign = leg.action === "buy" ? 1 : -1;
    total += sign * leg.entry_price * leg.contracts * 100;
  }
  return Math.round(total * 100) / 100;
}
