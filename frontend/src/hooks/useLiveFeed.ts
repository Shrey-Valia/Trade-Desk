import { useMemo } from "react";

import { useTrades } from "@/hooks/useTrades";
import { useWatchlist } from "@/hooks/useWatchlist";
import { buildFeedEvents } from "@/lib/feed";
import type { FeedEvent } from "@/types/feed";

export interface LiveFeed {
  events: FeedEvent[];
  isLoading: boolean;
  isError: boolean;
  /** Newest of the two source queries' fetch times (epoch ms), for the
   *  header's "refreshed" relative-time label. */
  updatedAt: number;
  refetch: () => void;
}

/**
 * The Live Feed tape: the global watchlist signals merged with the
 * user's own trade opens/closes into one descending-by-time list.
 *
 * Composite hook (same shape as useCombineStatus) — reuses the shared
 * watchlist (30s) and trades queries; opts the trades query into a 15s
 * poll so fills surface live without waiting on a mutation. Partial-data
 * tolerant: if one source errors we still render the other (e.g. show
 * fills even when the watchlist feed is throttled).
 */
export function useLiveFeed(): LiveFeed {
  const watchlistQuery = useWatchlist();
  const tradesQuery = useTrades({}, { refetchInterval: 15_000 });

  const events = useMemo(
    () => buildFeedEvents(watchlistQuery.data, tradesQuery.data?.trades ?? []),
    [watchlistQuery.data, tradesQuery.data],
  );

  const isLoading =
    watchlistQuery.isLoading && tradesQuery.isLoading && events.length === 0;
  const isError =
    watchlistQuery.isError && tradesQuery.isError && events.length === 0;
  const updatedAt = Math.max(
    watchlistQuery.dataUpdatedAt ?? 0,
    tradesQuery.dataUpdatedAt ?? 0,
  );

  return {
    events,
    isLoading,
    isError,
    updatedAt,
    refetch: () => {
      watchlistQuery.refetch();
      tradesQuery.refetch();
    },
  };
}
