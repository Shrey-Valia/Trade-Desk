import { z } from "zod";

export const ZeroDteLegQuoteSchema = z.object({
  symbol: z.string(),
  strike: z.number(),
  side: z.enum(["call", "put"]),
  bid: z.number().nullable(),
  ask: z.number().nullable(),
  last: z.number().nullable(),
  iv: z.number().nullable(),
});
export type ZeroDteLegQuote = z.infer<typeof ZeroDteLegQuoteSchema>;

export const ZeroDteChainSchema = z.object({
  underlying: z.string(),
  spot: z.number(),
  expiry: z.string(),
  strike: z.number(),
  call: ZeroDteLegQuoteSchema,
  put: ZeroDteLegQuoteSchema,
  t_years_to_close: z.number(),
  session_close_iso: z.string(),
  indicative: z.boolean(),
  notice: z.string(),
});
export type ZeroDteChain = z.infer<typeof ZeroDteChainSchema>;

export const STARTING_BALANCE = 10_000;

// -- Chain table (trading-ticket grid) --------------------------------------

export const ChainStrikeRowSchema = z.object({
  strike: z.number(),
  call_price: z.number(),
  call_source: z.enum(["quote", "bs"]),
  call_open_interest: z.number().nullable(),
  put_price: z.number(),
  put_source: z.enum(["quote", "bs"]),
  put_open_interest: z.number().nullable(),
  is_atm: z.boolean(),
  // Per-share display greeks from the backend BS engine (delta unitless,
  // theta per-day). Default 0 keeps the schema tolerant of older payloads.
  call_delta: z.number().default(0),
  call_theta: z.number().default(0),
  put_delta: z.number().default(0),
  put_theta: z.number().default(0),
  // Per-contract implied vol back-solved from the quote mid (smile/skew
  // visibility). null/absent on BS-fallback sides and older payloads.
  call_iv: z.number().nullable().optional(),
  put_iv: z.number().nullable().optional(),
  // Per-side NBBO + session volume. nullable().optional() so the UI works
  // both before and after the backend starts sending them; null = no live
  // quote on that side (the mid/model price above is the fallback).
  call_bid: z.number().nullable().optional(),
  call_ask: z.number().nullable().optional(),
  put_bid: z.number().nullable().optional(),
  put_ask: z.number().nullable().optional(),
  call_volume: z.number().nullable().optional(),
  put_volume: z.number().nullable().optional(),
});
export type ChainStrikeRow = z.infer<typeof ChainStrikeRowSchema>;

export const ChainTableSchema = z.object({
  underlying: z.string(),
  spot: z.number(),
  expiry: z.string(),
  atm_strike: z.number(),
  iv_used: z.number(),
  iv_source: z.enum(["implied_atm", "default"]),
  rows: z.array(ChainStrikeRowSchema),
  t_years_to_close: z.number(),
  session_close_iso: z.string(),
  /** False when the table shows a LATER expiration than today (multi-expiry
   *  browsing): cells are display-only — opening remains strictly 0DTE. */
  expiry_is_today: z.boolean().default(true),
  indicative: z.boolean(),
  notice: z.string(),
  /** Quote timestamp (ISO) — when the chain's prices were sourced. */
  as_of: z.string().nullable().optional(),
});
export type ChainTable = z.infer<typeof ChainTableSchema>;

// -- IV term structure (ATM IV per listed expiration) -----------------------

export const TermStructureSchema = z.object({
  symbol: z.string(),
  spot: z.number(),
  points: z.array(
    z.object({
      expiry: z.string(),
      dte: z.number().int(),
      atm_strike: z.number(),
      atm_iv: z.number().nullable(),
    }),
  ),
  /** far ATM IV − near ATM IV over the covered window; null <2 solved points. */
  slope: z.number().nullable(),
  shape: z.enum(["contango", "backwardation", "flat"]).nullable(),
});
export type TermStructure = z.infer<typeof TermStructureSchema>;

// -- Roll (atomic close + reopen at shifted strikes) ------------------------

export const RollOutSchema = z.object({
  closed: z.number().int(),
  opened: z.number().int(),
  /** $ booked closing the old position. */
  realized: z.number(),
  /** The NEW position's net entry ($, signed — debit positive). */
  net_debit_credit: z.number(),
});
export type RollOut = z.infer<typeof RollOutSchema>;

// -- Expirations (the chain browser's expiry selector) ----------------------

export const ExpirationsSchema = z.object({
  symbol: z.string(),
  expirations: z.array(
    z.object({
      expiry: z.string(), // ISO date
      dte: z.number().int(),
      is_today: z.boolean(),
    }),
  ),
});
export type Expirations = z.infer<typeof ExpirationsSchema>;

// -- Contract preview (the detail panel: payoff + greeks) -------------------

export const ContractPreviewSchema = z.object({
  symbol: z.string(),
  kind: z.enum(["leg", "straddle", "multi"]),
  side: z.enum(["call", "put"]).nullable(),
  strike: z.number(),
  contracts: z.number().int(),
  spot: z.number(),
  iv: z.number(),
  expiry: z.string(),
  dte_label: z.string(),
  /** Per-share net premium (debit > 0). */
  entry_price: z.number(),
  /** entry_price × 100 × contracts. */
  cost: z.number(),
  open_interest: z.number().nullable(),
  /** Underlying-price grid for the payoff curve (x-axis). */
  prices: z.array(z.number()),
  /** $ P&L at t_now across `prices`. */
  payoff_today: z.array(z.number()),
  /** $ P&L at expiration across `prices`. */
  payoff_expiration: z.array(z.number()),
  /** Expiration break-even price(s). */
  breakevens: z.array(z.number()),
  /** null = unbounded upside. */
  max_profit: z.number().nullable(),
  /** null = unbounded downside (net short calls — multi-leg preview only). */
  max_loss: z.number().nullable(),
  greeks: z.object({
    delta: z.number(),
    gamma: z.number(),
    theta: z.number(),
    vega: z.number(),
  }),
  // Closed-form model probabilities (risk-neutral lognormal, ATM IV).
  // prob_itm: finishes ITM at expiry (null for a straddle). pop_long /
  // pop_short: probability of profit at expiry per direction.
  // nullable().optional(): tolerant of payloads from before the backend
  // computed them.
  prob_itm: z.number().nullable().optional(),
  pop_long: z.number().nullable().optional(),
  pop_short: z.number().nullable().optional(),
});
export type ContractPreview = z.infer<typeof ContractPreviewSchema>;

export interface ContractPreviewInput {
  symbol: string;
  kind: "leg" | "straddle";
  side?: "call" | "put";
  strike: number;
  contracts: number;
  /** Pre-trade time scrubber: what-if minutes-to-close for the T+0 curve
   *  and greeks (entry pricing stays at the real now). Omitted = now. */
  minutes_to_close?: number | null;
}

// -- WS5: multi-leg strategy builder ----------------------------------------

/** One leg of a custom/preset multi-leg structure. `ratio` scales the leg
 *  within the structure (e.g. butterfly body = 2); actual contracts =
 *  ratio × the request's base `contracts`. */
export interface MultiLegSpec {
  side: "call" | "put";
  action: "buy" | "sell";
  strike: number;
  ratio?: number;
}

export interface OpenMultiLegInput {
  symbol: string;
  contracts: number;
  legs: MultiLegSpec[];
  /** Label: "vertical" | "iron_condor" | "butterfly" | "custom". */
  strategy?: string;
  /** market (default) fills now at server pricing; "limit" rests as a
   *  working order until the structure's NET mark crosses `limit_price`.
   *  Omitted entirely for market opens (wire-compatible with older backends). */
  order_type?: "market" | "limit";
  /** NET premium per 1× structure ($/share): debit positive, credit negative. */
  limit_price?: number | null;
  stop_loss?: number | null;
  take_profit?: number | null;
  /** Optional premium-exit multiples of the entry premium — TP/SL on the
   *  structure's net mark (fraction of the credit for net-credit opens). */
  tp_premium_mult?: number | null;
  sl_premium_mult?: number | null;
}

// -- WS5: Monte-Carlo scenario / backtest -----------------------------------

export interface MonteCarloLeg {
  side: "call" | "put";
  action: "buy" | "sell";
  strike: number;
  contracts: number;
  entry_price: number;
}

export interface MonteCarloInput {
  /** Reference an owned open trade OR pass explicit `legs`. */
  trade_id?: number | null;
  legs?: MonteCarloLeg[];
  spot: number;
  sigma: number;
  horizon_days: number;
  rate?: number;
  drift?: number | null;
  paths?: number;
  seed?: number | null;
}

export const MonteCarloResultSchema = z.object({
  paths: z.number().int(),
  horizon_days: z.number(),
  spot: z.number(),
  sigma: z.number(),
  drift: z.number(),
  cost_basis: z.number(),
  prob_profit: z.number(),
  expected_pnl: z.number(),
  median_pnl: z.number(),
  pnl_p05: z.number(),
  pnl_p95: z.number(),
  max_simulated_loss: z.number(),
  max_simulated_profit: z.number(),
  var_95: z.number(),
  expected_terminal_price: z.number(),
  hist_bin_edges: z.array(z.number()),
  hist_counts: z.array(z.number().int()),
  sample_terminal_prices: z.array(z.number()),
});
export type MonteCarloResult = z.infer<typeof MonteCarloResultSchema>;
