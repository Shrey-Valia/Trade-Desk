import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { fetchMultiLegPreview } from "@/lib/api";
import type { MultiLegSpec } from "@/types/zerodte";

/**
 * Risk graph for the builder's structure AS SUBMITTED (short legs negative):
 * payoff curves, breakevens, max profit/loss, POP. Re-fetches as the legs
 * change (the leg list is folded into the query key) and refreshes on the
 * chain's cadence so the graph tracks the live net premium.
 */
export function useMultiLegPreview(
  symbol: string,
  legs: MultiLegSpec[],
  contracts: number,
) {
  return useQuery({
    queryKey: ["preview-multi", symbol, JSON.stringify(legs), contracts],
    queryFn: () => fetchMultiLegPreview({ symbol, contracts, legs }),
    enabled: legs.length >= 2,
    staleTime: 5_000,
    refetchInterval: 10_000,
    placeholderData: keepPreviousData,
    retry: 1,
  });
}
