import { useQuery } from "@tanstack/react-query";

import { fetchJournalAnalytics, type JournalAnalyticsFilters } from "@/lib/api";

/**
 * Cross-trade aggregations for the analytics route. Cheap — the math
 * runs over a few hundred rows at most. Filters are part of the query
 * key so changing a filter triggers a fresh fetch.
 */
export function useJournalAnalytics(filters: JournalAnalyticsFilters = {}) {
  return useQuery({
    queryKey: ["journal-analytics", filters],
    queryFn: () => fetchJournalAnalytics(filters),
    staleTime: 30_000,
    placeholderData: (prev) => prev,
  });
}
