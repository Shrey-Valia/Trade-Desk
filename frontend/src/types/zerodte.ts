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
  indicative: z.boolean(),
  notice: z.string(),
});
export type ChainTable = z.infer<typeof ChainTableSchema>;
