import { useQuery } from "@tanstack/react-query";
import { fetchLiquidUniverse, fetchZeroDteUniverse } from "@/lib/api";

/**
 * The set of prewarmed liquid tickers. Driven by the backend so the list
 * stays in sync with the prewarm job's coverage. Stale-time is long
 * because the universe rarely changes within a session.
 */
export function useLiquidUniverse() {
  return useQuery({
    queryKey: ["market", "liquid_universe"],
    queryFn: fetchLiquidUniverse,
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });
}

/**
 * The 0DTE-eligible allowlist. Trade Desk is 0DTE-only, so the symbol
 * search restricts to this set — picking anything else just produces a
 * 409 on open. Source of truth lives in backend config.zero_dte_universe.
 */
export function useZeroDteUniverse() {
  return useQuery({
    queryKey: ["market", "zerodte_universe"],
    queryFn: fetchZeroDteUniverse,
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });
}
