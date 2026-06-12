import { useQuery } from "@tanstack/react-query";

import { fetchAccountState } from "@/lib/api";

const ACCOUNT_STATE_KEY = ["account", "state"] as const;

/**
 * Active combine snapshot (balance/MLL/DLL/HWM + identity + the
 * user's combine list for the header selector).
 *
 * Polls every 5s while the page is open so HWM/MLL stay live as
 * trades close. retry off: the error states (401 logged out, 404 no
 * active combine) won't fix themselves by retrying, and the poll
 * re-checks anyway.
 *
 * Combine switching lives in useActivateCombine (hooks/useCombines);
 * the legacy tier-switch mutation was retired with the TierPill.
 */
export function useAccountState() {
  return useQuery({
    queryKey: ACCOUNT_STATE_KEY,
    queryFn: fetchAccountState,
    refetchInterval: 5_000,
    staleTime: 5_000,
    retry: false,
  });
}
