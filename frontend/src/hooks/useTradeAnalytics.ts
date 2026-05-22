import { useQuery } from "@tanstack/react-query";

import { fetchTradeAnalytics } from "@/lib/api";

/**
 * Pulls /api/journal/trades/{id}/analytics. When `dteOverride` is null
 * the backend returns the "today" snapshot (no scrubber); when set, it
 * returns the position state at that DTE.
 *
 * staleTime kept short so live spot / IV changes flow through, but
 * placeholderData='keepPreviousData' avoids the empty flicker when the
 * scrubber moves (we don't want the chart's BE line to disappear for
 * 200ms between scrubber positions).
 */
export function useTradeAnalytics(
  tradeId: number | null,
  dteOverride: number | null,
) {
  return useQuery({
    queryKey: ["trade-analytics", tradeId, dteOverride],
    queryFn: () => fetchTradeAnalytics(tradeId as number, dteOverride),
    enabled: tradeId != null,
    staleTime: 10_000,
    placeholderData: (prev) => prev,
  });
}
