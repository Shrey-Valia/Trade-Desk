import { useQuery } from "@tanstack/react-query";

import { searchTickers } from "@/lib/api";

/**
 * Partial-match ticker search. Query stays disabled until the user
 * has typed at least one character. Cache results per query so
 * typing-then-backspace doesn't re-fetch the same prefix.
 */
export function useTickerSearch(q: string) {
  const trimmed = q.trim();
  return useQuery({
    queryKey: ["ticker", "search", trimmed],
    queryFn: () => searchTickers(trimmed),
    enabled: trimmed.length > 0,
    staleTime: 30_000,
  });
}
