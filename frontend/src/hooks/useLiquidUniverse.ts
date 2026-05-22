import { useQuery } from "@tanstack/react-query";
import { fetchLiquidUniverse } from "@/lib/api";

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
