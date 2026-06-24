import { useQuery } from "@tanstack/react-query";

import { fetchTickerIndicators } from "@/lib/api";
import type { ChartTimeframe } from "@/types/chart";

/**
 * Technical-indicator overlays for the chart. Keyed on (symbol,
 * timeframe, set) so toggling an indicator on/off refetches only the
 * new set; the query is disabled when no indicators are enabled so a
 * clean chart issues no request.
 *
 * staleTime/refetchInterval mirror the bars query (60s) — indicators are
 * derived from the same bars, so they go stale on the same cadence.
 */
export function useTickerIndicators(
  symbol: string | null,
  timeframe: ChartTimeframe,
  set: string,
) {
  return useQuery({
    queryKey: ["ticker", "indicators", symbol, timeframe, set],
    queryFn: () => fetchTickerIndicators(symbol as string, timeframe, set),
    enabled: !!symbol && set.length > 0,
    staleTime: 60_000,
    refetchInterval: 60_000,
    placeholderData: (prev) => prev,
  });
}
