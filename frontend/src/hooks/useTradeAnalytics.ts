import { useQuery } from "@tanstack/react-query";

import { fetchTradeAnalytics } from "@/lib/api";

/**
 * /api/journal/trades/{id}/analytics — drives the on-chart breakeven
 * overlay and the payoff panel.
 *
 * Two scrubber modes:
 *   * `dteOverride` — integer days remaining. Multi-day positions.
 *   * `elapsedHours` — fractional hours since entry. 0DTE positions
 *     only (the backend ignores it for non-0DTE trades).
 *
 * When `intraday` is true, react-query polls every 5s so the live mark
 * + intraday breakevens update without a page refresh; with the
 * scrubber off-live we still tick because spot moves underneath us.
 * For multi-day positions polling is off (inputs change on minute scale
 * at fastest) — those refresh on focus/refetch as before.
 *
 * placeholderData='keepPreviousData' so the BE line doesn't disappear
 * for 200ms between scrubber positions or polling ticks.
 */
export function useTradeAnalytics(
  tradeId: number | null,
  dteOverride: number | null,
  options: { intraday?: boolean; elapsedHours?: number | null } = {},
) {
  const { intraday = false, elapsedHours = null } = options;
  return useQuery({
    queryKey: [
      "trade-analytics",
      tradeId,
      dteOverride,
      intraday ? "intraday" : "day",
      intraday ? elapsedHours : null,
    ],
    queryFn: () =>
      fetchTradeAnalytics(tradeId as number, {
        dteOverride,
        elapsedHours: intraday ? elapsedHours : null,
      }),
    enabled: tradeId != null,
    staleTime: intraday ? 3_000 : 10_000,
    refetchInterval: intraday ? 5_000 : false,
    placeholderData: (prev) => prev,
  });
}
