import { useQuery } from "@tanstack/react-query";

import { fetchTickerNews } from "@/lib/api";

/**
 * Ticker-scoped news for the bottom-row NEWS panel.
 *
 * queryKey is scoped to the symbol so switching tickers fetches fresh and
 * caches per symbol. Low request volume by design: staleTime matches the
 * server's 5-min cache and we refetch only every 5 min (no aggressive
 * poll) — the free Alpaca feed 429s under load.
 *
 * A 503 from the backend (upstream error / rate-limit) throws in the
 * fetcher → `isError`, which the panel renders distinctly from an empty
 * (but successful) `items: []`.
 */
export function useTickerNews(symbol: string | null) {
  return useQuery({
    queryKey: ["news", symbol],
    queryFn: () => fetchTickerNews(symbol as string),
    enabled: !!symbol,
    staleTime: 5 * 60_000,
    refetchInterval: 5 * 60_000,
    refetchOnWindowFocus: false,
    // Don't thrash the throttled feed with retries — one gentle retry.
    retry: 1,
    placeholderData: (prev) => prev,
  });
}
