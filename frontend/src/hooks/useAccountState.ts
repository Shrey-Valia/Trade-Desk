import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchAccountState, switchAccountTier } from "@/lib/api";
import { useActivePosition } from "@/stores/activePosition";

const ACCOUNT_STATE_KEY = ["account", "state"] as const;

/**
 * Active combine tier + balance/MLL/HWM snapshot.
 *
 * Polls every 5s while the page is open so HWM/MLL stay live as
 * trades close. Same cadence as the chart bars / ticker detail.
 */
export function useAccountState() {
  return useQuery({
    queryKey: ACCOUNT_STATE_KEY,
    queryFn: fetchAccountState,
    refetchInterval: 5_000,
    staleTime: 5_000,
  });
}

/**
 * Switch the active combine tier. Invalidates trades + account state,
 * AND clears the active position so a trade on the prior tier doesn't
 * keep rendering on the new tier's chart/header.
 */
export function useSwitchTier() {
  const queryClient = useQueryClient();
  const clearActive = useActivePosition((s) => s.clear);
  return useMutation({
    mutationFn: (tier: string) => switchAccountTier(tier),
    onSuccess: (data) => {
      queryClient.setQueryData(ACCOUNT_STATE_KEY, data);
      queryClient.invalidateQueries({ queryKey: ["journal", "trades"] });
      // Cross-tier position contamination guard. Without this, an
      // active trade from tier A persists across the switch to tier B
      // and surfaces on the chart, OPEN POSITION column, and UP&L.
      clearActive();
    },
  });
}
