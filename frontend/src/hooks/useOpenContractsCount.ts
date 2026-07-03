import { useMemo } from "react";

import { useAccountState } from "@/hooks/useAccountState";
import { useTrades } from "@/hooks/useTrades";
import type { Trade } from "@/types/journal";

/**
 * Shared scaling-cap math — the single source of truth for "how many
 * contracts are already on".
 *
 * The scaling plan caps TOTAL open size, SUM-OF-LEGS across every open and
 * working trade (a 5-lot straddle is 10 contracts), matching the server's
 * enforcement. TradeTicket and RightChain's QuickOrder both size off this so
 * a one-click order can never exceed what the server would accept.
 *
 * Scope: the ACTIVE combine. Trades carry only their tier (the payload has
 * no per-trade combine id), so the count filters by the active combine's
 * tier — the closest client-side approximation; the server remains the
 * per-combine authority on open.
 */
export function sumOpenContracts(trades: Trade[], tier: string): number {
  return trades
    .filter(
      (t) =>
        (t.status === "open" || t.status === "working") &&
        (t.tier ?? "50K") === tier,
    )
    .reduce(
      (sum, t) =>
        sum +
        (t.legs.length
          ? t.legs.reduce((a, l) => a + (l.contracts ?? 1), 0)
          : 1),
      0,
    );
}

export interface OpenContractsCount {
  /** Contracts already open/working on the active combine (sum-of-legs). */
  openContracts: number;
  /** Scaling-plan max TOTAL open size (server-enforced too). */
  maxContracts: number;
  /** Remaining capacity = maxContracts − openContracts, floored at 0. */
  remaining: number;
  activeTier: string;
}

export function useOpenContractsCount(): OpenContractsCount {
  const { data: accountState } = useAccountState();
  const { data: tradesData } = useTrades();
  // Default high until account state loads so the UI never wrongly blocks.
  const maxContracts = accountState?.max_contracts ?? 99;
  const activeTier = accountState?.active_tier ?? "50K";
  const openContracts = useMemo(
    () => sumOpenContracts(tradesData?.trades ?? [], activeTier),
    [tradesData, activeTier],
  );
  return {
    openContracts,
    maxContracts,
    remaining: Math.max(0, maxContracts - openContracts),
    activeTier,
  };
}
