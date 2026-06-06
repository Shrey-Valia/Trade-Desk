import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  addStar,
  fetchPopularTickers,
  fetchStars,
  logTickerSelection,
  removeStar,
} from "@/lib/api";
import type { StarsResponse } from "@/types/search";

const STARS_KEY = ["user", "stars"] as const;
const POPULAR_KEY = ["ticker", "popular"] as const;

/**
 * User's starred symbols — server-persisted list, oldest-first.
 *
 * Stable cache through the session: stars rarely change, so polling
 * adds nothing. The mutation hooks below invalidate on change.
 */
export function useStars() {
  return useQuery({
    queryKey: STARS_KEY,
    queryFn: fetchStars,
    staleTime: Infinity,
  });
}

/**
 * Toggle a star with optimistic update.
 *
 * Optimistic so the star icon flips immediately on click — the server
 * round-trip would otherwise show a 100-300ms lag where the user
 * doesn't know whether the click registered. On error, react-query
 * reverts via onError + previous-cache restore.
 */
export function useToggleStar() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ symbol, currentlyStarred }: {
      symbol: string;
      currentlyStarred: boolean;
    }) => {
      return currentlyStarred ? removeStar(symbol) : addStar(symbol);
    },
    onMutate: async ({ symbol, currentlyStarred }) => {
      await qc.cancelQueries({ queryKey: STARS_KEY });
      const prev = qc.getQueryData<StarsResponse>(STARS_KEY);
      const nextSymbols = currentlyStarred
        ? (prev?.symbols ?? []).filter((s) => s !== symbol)
        : [...(prev?.symbols ?? []), symbol];
      qc.setQueryData<StarsResponse>(STARS_KEY, { symbols: nextSymbols });
      return { prev };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) qc.setQueryData(STARS_KEY, ctx.prev);
    },
    onSettled: (data) => {
      // Server response is authoritative — replace whatever the
      // optimistic update produced with the actual list.
      if (data) qc.setQueryData(STARS_KEY, data);
    },
  });
}

/**
 * Curated popular-ticker slate — 8 names with live 0DTE flags.
 *
 * Cached 5 minutes: the backend chain-availability check has the same
 * TTL, so polling more aggressively just wastes round-trips.
 */
export function usePopularTickers() {
  return useQuery({
    queryKey: POPULAR_KEY,
    queryFn: fetchPopularTickers,
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * Fire-and-forget selection log — call when the user picks a ticker
 * from the modal. Backend writes one ticker_selections row; we don't
 * await the response (no UI needs it).
 */
export function logSelection(symbol: string): void {
  void logTickerSelection(symbol);
}
