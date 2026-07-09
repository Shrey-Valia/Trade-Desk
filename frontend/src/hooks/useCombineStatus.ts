import { useMemo } from "react";
import { keepPreviousData, useQueries } from "@tanstack/react-query";

import { useAccountState } from "@/hooks/useAccountState";
import { useTrades } from "@/hooks/useTrades";
import { fetchTradeAnalytics } from "@/lib/api";
import { isActiveCombineTrade } from "@/lib/combineScope";
import type { TierKey } from "@/types/account";
import { isZeroDteTrade } from "@/types/journal";

export interface CombineStatus {
  loading: boolean;
  /** Live combine status. FAILED = MLL floor breached (persisted once
   *  realized; shown live the instant URPL breaches). */
  status: "active" | "passed" | "failed";
  /** DLL hit today (realized + live URPL) → no further trading today. */
  dayLocked: boolean;
  /** Live net balance = realized balance + summed live URPL on this tier. */
  balanceLive: number;
  /** The FIXED-intraday MLL floor. */
  mllFloor: number;
  /** $ cushion of live balance above the floor (negative = breached). */
  mllCushion: number;
  /** Hero proximity 0..1: 1 = full trailing cushion, 0 = at/under floor. */
  mllProximity: number;
  /** Live DLL used today ($, ≥0) — realized loss + current URPL loss. */
  dllUsedLive: number;
  dllBudget: number;
  /** DLL switched OFF for the active tier — no day-lock / breach applies. */
  dllDisabled: boolean;
  // --- PASS / profit-target (the OTHER pole — how close to passing) ---
  /** True once the combine has PASSED (permanent). */
  passed: boolean;
  /** Realized profit needed to pass. */
  profitTarget: number;
  /** Realized profit so far. */
  realizedProfit: number;
  /** Live progress toward target = realized + live URPL (display only;
   *  passing persists on realized). */
  targetProgressLive: number;
  /** 0..1 proximity to the target (live). */
  targetProximity: number;
  /** Realized target reached (the persisted basis). */
  targetMet: boolean;
  daysTraded: number;
  minTradingDays: number;
  minDaysMet: boolean;
  consistencyOk: boolean;
  /** Largest single day as a % of total realized profit (0 if no profit). */
  largestDayPct: number;
  /** When the target is met but the account hasn't passed, WHY (min-days
   *  or consistency); null otherwise. */
  passBlockedReason: string | null;
}

/**
 * The live combine-engine verdict — the MLL/DLL floors tested CONTINUOUSLY
 * against live net exposure (realized P&L + the reconciled per-position
 * live URPL summed across open positions on the active tier).
 *
 * The floors themselves (fixed intraday, re-baselined at the 5pm-PT
 * settlement) come from the backend; this hook folds in the live URPL so
 * the breach can be seen in real time, not only on close. Drives the
 * header hero ("how close to blowing up") and the trade-ticket soft-gate.
 *
 * Zero new network: reuses the shared account-state, trades, and
 * per-position analytics queries (same keys the header already polls).
 */
export function useCombineStatus(): CombineStatus {
  const { data: account } = useAccountState();
  const { data: tradesData } = useTrades();
  const activeTier = (account?.active_tier ?? "50K") as TierKey;
  const combineId = account?.combine_id;

  const openPositions = useMemo(
    () =>
      (tradesData?.trades ?? []).filter(
        (t) => t.status === "open" && isActiveCombineTrade(t, combineId, activeTier),
      ),
    [tradesData, activeTier, combineId],
  );
  const positionAnalytics = useQueries({
    queries: openPositions.map((t) => {
      const intraday = isZeroDteTrade(t);
      return {
        queryKey: ["trade-analytics", t.id, null, intraday ? "intraday" : "day", null],
        queryFn: () => fetchTradeAnalytics(t.id, { dteOverride: null, elapsedHours: null }),
        staleTime: intraday ? 3_000 : 10_000,
        refetchInterval: intraday ? 5_000 : (false as const),
        placeholderData: keepPreviousData,
      };
    }),
  });
  const liveUpl = useMemo(
    () => positionAnalytics.reduce((sum, q) => sum + (q.data?.unrealized_pnl ?? 0), 0),
    [positionAnalytics],
  );

  const tier = account?.tiers.find((t) => t.key === activeTier);
  const trailingDistance = tier?.trailing_distance ?? 1;
  const mllFloor = account?.mll ?? 0;
  const dllBudget = account?.dll_budget ?? 0;
  const realizedBalance = account?.balance ?? 0;

  const balanceLive = realizedBalance + liveUpl;
  const mllCushion = balanceLive - mllFloor;
  const mllProximity =
    trailingDistance > 0 ? Math.max(0, Math.min(1, mllCushion / trailingDistance)) : 0;

  // DLL-off toggle: when the active tier has the DLL switched off, no
  // day-lock / breach applies (only the MLL floor binds).
  const dllDisabled = account?.dll_disabled ?? false;
  // Live DLL: today's realized loss (backend) + any current URPL loss.
  const dllUsedLive = Math.max(0, (account?.dll_used ?? 0) + Math.max(0, -liveUpl));

  // FAILED is sticky once the backend persists it (realized breach), and
  // shown live the instant the URPL-inclusive balance touches the floor.
  const liveFailed = !!account && balanceLive <= mllFloor;
  const status: CombineStatus["status"] =
    account?.status === "failed" || liveFailed
      ? "failed"
      : account?.status === "passed"
        ? "passed"
        : "active";
  // Guard against a FALSE day-lock while account state is loading or 404s:
  // with no account, dllBudget and dllUsedLive are both 0, so `0 >= 0` would
  // otherwise flash (and permanently show, on 404) a red "DAY LOCK" banner and
  // disable the ticket. Require a real account with a positive budget for the
  // live-DLL branch; the backend's own `day_locked` flag still counts.
  const dayLocked =
    !!account &&
    !dllDisabled &&
    ((account.day_locked ?? false) || (dllBudget > 0 && dllUsedLive >= dllBudget));

  // PASS / profit-target progress. Passing PERSISTS on realized profit
  // (backend); live URPL only moves the displayed proximity.
  const passed = account?.status === "passed";
  const profitTarget = account?.profit_target ?? 0;
  const realizedProfit = account?.realized_pnl ?? 0;
  const targetProgressLive = realizedProfit + liveUpl;
  const targetProximity =
    profitTarget > 0 ? Math.max(0, Math.min(1, targetProgressLive / profitTarget)) : 0;
  const targetMet = profitTarget > 0 && realizedProfit >= profitTarget;
  const daysTraded = account?.days_traded ?? 0;
  const minTradingDays = account?.min_trading_days ?? 2;
  const minDaysMet = daysTraded >= minTradingDays;
  const consistencyOk = account?.consistency_ok ?? true;
  const largestDayPct =
    realizedProfit > 0 ? ((account?.largest_day_profit ?? 0) / realizedProfit) * 100 : 0;

  // Why the target is met but the account hasn't passed yet.
  let passBlockedReason: string | null = null;
  if (targetMet && !passed) {
    if (!minDaysMet) {
      const remaining = Math.max(0, minTradingDays - daysTraded);
      passBlockedReason = `target met — ${remaining} more trading day${
        remaining === 1 ? "" : "s"
      } required`;
    } else if (!consistencyOk) {
      passBlockedReason = `consistency rule not met — largest day is ${Math.round(
        largestDayPct,
      )}% of profit`;
    }
  }

  return {
    loading: !account,
    status,
    dayLocked,
    balanceLive,
    mllFloor,
    mllCushion,
    mllProximity,
    dllUsedLive,
    dllBudget,
    dllDisabled,
    passed,
    profitTarget,
    realizedProfit,
    targetProgressLive,
    targetProximity,
    targetMet,
    daysTraded,
    minTradingDays,
    minDaysMet,
    consistencyOk,
    largestDayPct,
    passBlockedReason,
  };
}
