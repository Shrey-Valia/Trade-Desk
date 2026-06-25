import { z } from "zod";

import { TradeOutSchema, type Trade } from "@/types/journal";

const API_BASE = "";

/** Single-leg open: long/short call/put at the given strike, expiring
 *  today (must be 0DTE). Backend creates a Trade with strategy=
 *  long_call / long_put / short_call / short_put so the existing
 *  analytics + chart-overlay path renders it unchanged. */
export async function openZeroDteLeg(input: {
  symbol: string;
  side: "call" | "put";
  action: "buy" | "sell";
  strike: number;
  entry_price: number;
  contracts?: number;
  /** market (default) fills now; limit/stop/stop_limit place a working order. */
  order_type?: "market" | "limit" | "stop" | "stop_limit";
  /** Option-premium trigger for a limit/stop order (the resting limit for stop_limit). */
  limit_price?: number | null;
  /** Option-premium arm level for a stop_limit order. */
  stop_price?: number | null;
  /** Time-in-force for a working order: 'gtc' (default) rests; 'day' expires next session. */
  time_in_force?: "day" | "gtc";
  /** Optional trailing-stop EXIT distance ($/share off the favorable mark). */
  trail_amount?: number | null;
  /** Optional SL/TP brackets (underlying price levels). */
  stop_loss?: number | null;
  take_profit?: number | null;
}): Promise<Trade> {
  const res = await fetch(`${API_BASE}/api/zerodte/open-leg`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    // Session-cookie auth — open-leg is gated by get_active_combine, so
    // without this the POST is anonymous and 401s "not authenticated"
    // even when the user is signed in. Mirrors api.ts's mutate().
    credentials: "include",
    body: JSON.stringify({
      symbol: input.symbol,
      side: input.side,
      action: input.action,
      strike: input.strike,
      entry_price: input.entry_price,
      contracts: input.contracts ?? 1,
      order_type: input.order_type ?? "market",
      time_in_force: input.time_in_force ?? "gtc",
      limit_price: input.limit_price ?? null,
      stop_price: input.stop_price ?? null,
      trail_amount: input.trail_amount ?? null,
      stop_loss: input.stop_loss ?? null,
      take_profit: input.take_profit ?? null,
    }),
  });
  if (!res.ok) {
    // Surface the backend's detail message so the UI can show "market closed"
    // and "0DTE only" reasons clearly rather than a generic failure string.
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* non-json body */
    }
    throw new Error(detail);
  }
  return TradeOutSchema.parse(await res.json());
}

// re-export for symmetry with other tiny api wrappers in lib/
export const ZeroDteOpenLegResponseSchema = z.object({ trade: TradeOutSchema });

export const FlattenResultSchema = z.object({
  closed: z.array(z.number().int()),
  opened: z.array(z.number().int()).default([]),
  realized: z.number(),
});
export type FlattenResult = z.infer<typeof FlattenResultSchema>;

async function _postZerodte(path: string): Promise<FlattenResult> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* non-json body */
    }
    throw new Error(detail);
  }
  return FlattenResultSchema.parse(await res.json());
}

/** Close EVERY open position on the active combine at the live mark. */
export function flattenPositions(): Promise<FlattenResult> {
  return _postZerodte("/api/zerodte/flatten");
}

/** Flatten then re-open the OPPOSITE side of each position. */
export function reversePositions(): Promise<FlattenResult> {
  return _postZerodte("/api/zerodte/reverse");
}
