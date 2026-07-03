import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  activateAccount,
  activateCombine,
  archiveCombine,
  fetchCombineEvents,
  fetchCombines,
  purchaseCombine,
  renameCombine,
  requestPayout,
  resetCombine,
  updateCopyConfig,
} from "@/lib/api";
import { useActivePosition } from "@/stores/activePosition";
import { toast } from "@/stores/toast";
import type { CopyConfigInput, PurchaseInput } from "@/types/combine";

const errMsg = (e: unknown) => (e as Error)?.message || "Something went wrong";

export const COMBINES_KEY = ["combines"] as const;
export const COMBINE_EVENTS_KEY = ["combines", "events"] as const;
const ACCOUNT_STATE_KEY = ["account", "state"] as const;

export function useCombines() {
  return useQuery({
    queryKey: COMBINES_KEY,
    queryFn: fetchCombines,
    staleTime: 10_000,
  });
}

/** Recent lifecycle events (funded/failed/settled/reset/payout). Polls so
 *  the dashboard live-feed surfaces milestones as the engine writes them. */
export function useCombineEvents() {
  return useQuery({
    queryKey: COMBINE_EVENTS_KEY,
    queryFn: fetchCombineEvents,
    refetchInterval: 15_000,
    staleTime: 10_000,
  });
}

export function usePurchaseCombine() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: PurchaseInput) => purchaseCombine(input),
    onSuccess: (combine) => {
      qc.invalidateQueries({ queryKey: COMBINES_KEY });
      // First purchase auto-activates server-side → header state changes.
      qc.invalidateQueries({ queryKey: ACCOUNT_STATE_KEY });
      toast.success(`${combine.name} is ready to trade.`);
    },
    onError: (e) => toast.error(errMsg(e)),
  });
}

export function useRenameCombine() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { id: number; name: string }) =>
      renameCombine(args.id, args.name),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: COMBINES_KEY });
      qc.invalidateQueries({ queryKey: ACCOUNT_STATE_KEY });
    },
    onError: (e) => toast.error(errMsg(e)),
  });
}

export function useArchiveCombine() {
  const qc = useQueryClient();
  const clearActive = useActivePosition((s) => s.clear);
  return useMutation({
    mutationFn: (id: number) => archiveCombine(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: COMBINES_KEY });
      qc.invalidateQueries({ queryKey: ACCOUNT_STATE_KEY });
      qc.invalidateQueries({ queryKey: ["journal", "trades"] });
      clearActive();
      toast.info("Combine archived.");
    },
    onError: (e) => toast.error(errMsg(e)),
  });
}

/** Restart a failed evaluation. Refreshes combines + the active-combine
 *  state + the events feed (a reset writes a reset event). */
export function useResetCombine() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => resetCombine(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: COMBINES_KEY });
      qc.invalidateQueries({ queryKey: ACCOUNT_STATE_KEY });
      qc.invalidateQueries({ queryKey: COMBINE_EVENTS_KEY });
      toast.success("Evaluation reset — fresh start.");
    },
    onError: (e) => toast.error(errMsg(e)),
  });
}

/** Request a payout on a funded account (simulated). `amount` omitted
 *  books the max eligible. Gate rejections (409) carry the backend's
 *  human-readable detail — callers surface `mutation.error` verbatim. */
export function useRequestPayout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { id: number; amount?: number }) =>
      requestPayout(args.id, args.amount),
    onSuccess: (payout) => {
      qc.invalidateQueries({ queryKey: COMBINES_KEY });
      qc.invalidateQueries({ queryKey: ACCOUNT_STATE_KEY });
      qc.invalidateQueries({ queryKey: COMBINE_EVENTS_KEY });
      toast.success(`Payout requested — $${payout.amount.toLocaleString()}.`);
    },
    onError: (e) => toast.error(errMsg(e)),
  });
}

/** Activate a funded combine (simulated) — charges $149 on the activation
 *  path, $0 on no-activation — and unlocks payouts. */
export function useActivateAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => activateAccount(id),
    onSuccess: (combine) => {
      qc.invalidateQueries({ queryKey: COMBINES_KEY });
      qc.invalidateQueries({ queryKey: ACCOUNT_STATE_KEY });
      qc.invalidateQueries({ queryKey: COMBINE_EVENTS_KEY });
      toast.success(`${combine.name} activated — payouts unlocked.`);
    },
    onError: (e) => toast.error(errMsg(e)),
  });
}

/** Set copy trading (lead + followers). Refreshes the combines list. */
export function useUpdateCopyConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: CopyConfigInput) => updateCopyConfig(input),
    onSuccess: (data) => {
      qc.setQueryData(COMBINES_KEY, data);
      toast.success(
        data.copy_lead_combine_id == null
          ? "Copy trading off."
          : "Copy trading updated.",
      );
    },
    onError: (e) => toast.error(errMsg(e)),
  });
}

/** Mirrors the legacy useSwitchTier: the endpoint returns the full
 * account-state payload, which we swap straight into the cache so the
 * header updates without a refetch round-trip. */
export function useActivateCombine() {
  const qc = useQueryClient();
  const clearActive = useActivePosition((s) => s.clear);
  return useMutation({
    mutationFn: (id: number) => activateCombine(id),
    onSuccess: (state) => {
      qc.setQueryData(ACCOUNT_STATE_KEY, state);
      qc.invalidateQueries({ queryKey: COMBINES_KEY });
      qc.invalidateQueries({ queryKey: ["journal", "trades"] });
      // Guard against cross-combine position contamination, same as
      // the old tier switch.
      clearActive();
    },
    onError: (e) => toast.error(errMsg(e)),
  });
}
