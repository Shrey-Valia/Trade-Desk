import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { fetchPortfolioGreeks } from "@/lib/api";

/**
 * Net portfolio Greek book for the active combine — polls at the same 5s
 * cadence as the per-position analytics so the header exposure numbers move
 * with the panel. `enabled: false` while the book is flat (the caller knows
 * the open-position count) keeps the idle terminal quiet.
 */
export function usePortfolioGreeks(enabled: boolean) {
  return useQuery({
    queryKey: ["portfolio", "greeks"],
    queryFn: fetchPortfolioGreeks,
    enabled,
    staleTime: 3_000,
    refetchInterval: 5_000,
    placeholderData: keepPreviousData,
    retry: 1, // 503 while the feed is cold — the next poll retries anyway
  });
}
