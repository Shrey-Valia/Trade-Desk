import { useQuery } from "@tanstack/react-query";

import { fetchChainTable } from "@/lib/api";

/**
 * Windowed option chain around ATM for the trading ticket.
 *
 * staleTime: 5s — quotes move quickly intraday but most of the value
 * is in the structural layout (strike list, OI), which is daily.
 * refetchInterval: 10s — keeps the indicative prices fresh without
 * hammering the underlying alpaca call (server caches 5min).
 */
export function useChainTable(symbol: string | null, strikes: number = 15) {
  return useQuery({
    queryKey: ["zerodte", "chain", "table", symbol, strikes],
    queryFn: () => fetchChainTable(symbol as string, strikes),
    enabled: !!symbol,
    staleTime: 5_000,
    refetchInterval: 10_000,
    // Keep the previous data only when it belongs to the SAME symbol — a
    // smooth 10s same-symbol refetch shouldn't flicker, but on a symbol
    // SWITCH we must drop the prior chain so the new symbol's error/empty
    // state can't render the old symbol's rows. queryKey index 3 is `symbol`.
    placeholderData: (prev, prevQuery) =>
      prevQuery?.queryKey?.[3] === symbol ? prev : undefined,
  });
}
