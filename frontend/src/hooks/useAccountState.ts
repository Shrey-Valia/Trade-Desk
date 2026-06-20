import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchAccountState, fetchDllOverrides, updateDllOverrides } from "@/lib/api";
import { toast } from "@/stores/toast";

const ACCOUNT_STATE_KEY = ["account", "state"] as const;
const DLL_OVERRIDES_KEY = ["account", "dll-overrides"] as const;

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

/** The user's per-tier DLL overrides (server-enforced). Available even with
 *  zero combines, so the Settings editor works before any purchase. */
export function useDllOverrides() {
  return useQuery({
    queryKey: DLL_OVERRIDES_KEY,
    queryFn: fetchDllOverrides,
    staleTime: 60_000,
  });
}

/** Replace the per-tier DLL overrides. Refreshes the overrides + the active
 *  account snapshot (whose dll_budget reflects the new override). */
export function useUpdateDllOverrides() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (overrides: Record<string, number>) => updateDllOverrides(overrides),
    onSuccess: (saved) => {
      qc.setQueryData(DLL_OVERRIDES_KEY, saved);
      qc.invalidateQueries({ queryKey: ACCOUNT_STATE_KEY });
    },
    onError: (e) => toast.error((e as Error)?.message || "Couldn't save DLL limit"),
  });
}
