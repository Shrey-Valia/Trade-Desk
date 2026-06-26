import { useMemo } from "react";

import { useTrades } from "@/hooks/useTrades";
import type { Trade } from "@/types/journal";

/**
 * DOM-lite overlay support — index the resting (status="working") orders for
 * a symbol by strike + side so the option chain can paint a small badge
 * (qty + trigger) and an inline cancel "×" on the matching call/put cell.
 *
 * A working order is a {@link Trade} whose first leg carries the strike/side;
 * the trigger price is `limit_price` (the resting limit for stop/stop_limit,
 * the limit for a plain limit). Multiple resting orders can stack on the same
 * strike+side (e.g. a limit AND a stop), so each bucket is a list and the
 * badge aggregates quantity.
 *
 * Keyed by the SAME single-leg shape the chain trades in (one call or put per
 * strike). Multi-leg working orders (straddles) contribute each leg to its own
 * call/put bucket, which is the correct overlay behavior for the ladder.
 */
export interface WorkingOrderAtCell {
  /** The working-order trade this leg belongs to (for cancel + tooltip). */
  trade: Trade;
  side: "call" | "put";
  strike: number;
  /** Contracts on this leg (defaults to 1 for legacy payloads). */
  contracts: number;
  /** Resting trigger (limit for limit/stop_limit, stop level for stop). */
  trigger: number | null;
  /** market | limit | stop | stop_limit — drives the badge label. */
  orderType: Trade["order_type"];
  action: "buy" | "sell";
}

export interface WorkingOrdersByStrike {
  /** Map key = `${strike}:${side}` → the resting orders on that cell. */
  byCell: Map<string, WorkingOrderAtCell[]>;
  /** True while there is at least one resting order for the symbol. */
  hasAny: boolean;
}

export function cellKey(strike: number, side: "call" | "put"): string {
  return `${strike}:${side}`;
}

/**
 * Group `useTrades({status:"working"})` for `symbol` into a strike+side map.
 * Polls on the same 8s cadence as the Pending Orders strip so a badge appears
 * / clears promptly after a place or a monitor-driven fill. Symbol match is
 * case-insensitive and trimmed to mirror how the chain underlying is keyed.
 */
export function useWorkingOrdersByStrike(
  symbol: string | null,
): WorkingOrdersByStrike {
  const { data } = useTrades(
    { status: "working" },
    { refetchInterval: 8_000 },
  );

  return useMemo(() => {
    const byCell = new Map<string, WorkingOrderAtCell[]>();
    const want = symbol?.trim().toUpperCase() ?? null;
    if (!want) return { byCell, hasAny: false };

    for (const trade of data?.trades ?? []) {
      if (trade.symbol.trim().toUpperCase() !== want) continue;
      for (const leg of trade.legs) {
        const key = cellKey(leg.strike, leg.side);
        const bucket = byCell.get(key) ?? [];
        bucket.push({
          trade,
          side: leg.side,
          strike: leg.strike,
          contracts: leg.contracts ?? 1,
          // The trigger shown is the resting limit/stop the monitor watches.
          // stop arms at stop_price; for display the limit_price is the level
          // the user set in the ticket (seeded from stop_price for a stop).
          trigger: trade.limit_price ?? trade.stop_price ?? null,
          orderType: trade.order_type,
          action: leg.action,
        });
        byCell.set(key, bucket);
      }
    }
    return { byCell, hasAny: byCell.size > 0 };
  }, [data, symbol]);
}
