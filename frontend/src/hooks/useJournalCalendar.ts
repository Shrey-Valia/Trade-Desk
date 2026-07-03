import { useQuery } from "@tanstack/react-query";
import { create } from "zustand";

import { fetchJournalCalendar } from "@/lib/api";

/**
 * Journal account scope — which combine the calendar fetch is pinned to
 * (null = all accounts). JournalPage owns the ACTIVE / ALL toggle but the
 * calendar component owns its own fetch, so the scope crosses that
 * boundary here instead of through a prop the component doesn't take.
 */
interface JournalScopeState {
  combineId: number | null;
  setCombineId: (id: number | null) => void;
}

export const useJournalScope = create<JournalScopeState>((set) => ({
  combineId: null,
  setCombineId: (id) => set({ combineId: id }),
}));

/**
 * Monthly P&L calendar grid. `month` is "YYYY-MM" so the cache key
 * dedupes naturally — month-switching is just a prop change with
 * placeholderData smoothing the transition. The combine scope is part
 * of the key too, so switching accounts refetches the grid.
 */
export function useJournalCalendar(month: string, isPaper?: boolean | null) {
  const combineId = useJournalScope((s) => s.combineId);
  return useQuery({
    queryKey: ["journal-calendar", month, isPaper ?? null, combineId],
    queryFn: () => fetchJournalCalendar(month, isPaper, combineId),
    staleTime: 30_000,
    placeholderData: (prev) => prev,
  });
}
