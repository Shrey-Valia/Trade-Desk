import { useQuery } from "@tanstack/react-query";

import { fetchJournalCalendar } from "@/lib/api";

/**
 * Monthly P&L calendar grid. `month` is "YYYY-MM" so the cache key
 * dedupes naturally — month-switching is just a prop change with
 * placeholderData smoothing the transition.
 */
export function useJournalCalendar(month: string, isPaper?: boolean | null) {
  return useQuery({
    queryKey: ["journal-calendar", month, isPaper ?? null],
    queryFn: () => fetchJournalCalendar(month, isPaper),
    staleTime: 30_000,
    placeholderData: (prev) => prev,
  });
}
