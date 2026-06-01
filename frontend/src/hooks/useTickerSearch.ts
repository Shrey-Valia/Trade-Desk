import { useEffect, useState } from "react";

import { useQuery } from "@tanstack/react-query";

import { searchTickers } from "@/lib/api";

const DEBOUNCE_MS = 200;

/**
 * Debounce a string value. Returns the latest value once `delay`ms
 * have passed without further changes. Used to absorb fast typing on
 * the search box so the backend's chain-availability fan-out doesn't
 * trigger on every keystroke.
 */
function useDebouncedValue(value: string, delay: number): string {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(id);
  }, [value, delay]);
  return debounced;
}

/**
 * Partial-match ticker search.
 *
 * The query string is debounced at 200ms so a fast typer doesn't
 * trigger one request per keystroke against the backend's
 * chain-availability bulk path. React-query then caches by the
 * debounced string so backspacing into a prior prefix is free.
 *
 * `isFetching` reflects react-query's actual network state; the
 * search box reads it to render a "Searching…" empty state until
 * results arrive.
 */
export function useTickerSearch(q: string) {
  const trimmed = q.trim();
  const debounced = useDebouncedValue(trimmed, DEBOUNCE_MS);
  return useQuery({
    queryKey: ["ticker", "search", debounced],
    queryFn: () => searchTickers(debounced),
    enabled: debounced.length > 0,
    staleTime: 30_000,
  });
}
