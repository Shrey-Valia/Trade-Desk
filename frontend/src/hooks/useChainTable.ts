import { useCallback, useSyncExternalStore } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchChainTable, fetchExpirations } from "@/lib/api";
import type { ChainTable } from "@/types/zerodte";

/**
 * Windowed option chain around ATM for the trading ticket.
 *
 * staleTime: 5s — quotes move quickly intraday but most of the value
 * is in the structural layout (strike list, OI), which is daily.
 * refetchInterval: 10s — keeps the indicative prices fresh without
 * hammering the underlying alpaca call (server caches 5min).
 */
export function useChainTable(
  symbol: string | null,
  strikes: number = 15,
  expiry: string | null = null,
) {
  return useQuery({
    queryKey: ["zerodte", "chain", "table", symbol, strikes, expiry],
    queryFn: () => fetchChainTable(symbol as string, strikes, expiry),
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

/**
 * Listed expirations for the chain's expiry selector. Structural, slow-
 * moving data — refreshed every 5 min is plenty.
 */
export function useExpirations(symbol: string | null) {
  return useQuery({
    queryKey: ["zerodte", "expirations", symbol],
    queryFn: () => fetchExpirations(symbol as string),
    enabled: !!symbol,
    staleTime: 300_000,
    refetchInterval: 300_000,
  });
}

/**
 * PASSIVE read of the freshest chain table already in the query cache for
 * `symbol` — any strike span. Subscribes to cache updates but never fetches
 * or polls itself, so consumers (the header's expected-move pill) ride the
 * chain poll the ladder already runs instead of adding a duplicate request.
 * Null when nothing has been fetched yet (consumers hide).
 */
export function useCachedChainTable(symbol: string | null): ChainTable | null {
  const qc = useQueryClient();
  const subscribe = useCallback(
    (onStoreChange: () => void) => qc.getQueryCache().subscribe(onStoreChange),
    [qc],
  );
  const getSnapshot = useCallback((): ChainTable | null => {
    if (!symbol) return null;
    let best: ChainTable | null = null;
    let bestAt = -1;
    for (const q of qc
      .getQueryCache()
      .findAll({ queryKey: ["zerodte", "chain", "table", symbol] })) {
      const data = q.state.data as ChainTable | undefined;
      if (data && q.state.dataUpdatedAt > bestAt) {
        best = data;
        bestAt = q.state.dataUpdatedAt;
      }
    }
    return best;
  }, [qc, symbol]);
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}
