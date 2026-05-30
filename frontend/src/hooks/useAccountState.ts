import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchAccountState, switchAccountTier } from "@/lib/api";

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
 * Switch the active combine tier. Invalidates trades + account state
 * so the dashboard reflects the new tier's history immediately.
 */
export function useSwitchTier() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (tier: string) => switchAccountTier(tier),
    onSuccess: (data) => {
      queryClient.setQueryData(ACCOUNT_STATE_KEY, data);
      queryClient.invalidateQueries({ queryKey: ["journal", "trades"] });
    },
  });
}
