import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  activateCombine,
  archiveCombine,
  fetchCombineEvents,
  fetchCombines,
  purchaseCombine,
  renameCombine,
  requestPayout,
  resetCombine,
} from "@/lib/api";
import { useActivePosition } from "@/stores/activePosition";
import type { PurchaseInput } from "@/types/combine";

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
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: COMBINES_KEY });
      // First purchase auto-activates server-side → header state changes.
      qc.invalidateQueries({ queryKey: ACCOUNT_STATE_KEY });
    },
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
    },
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
    },
  });
}

/** Request a payout on a funded account (simulated). */
export function useRequestPayout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => requestPayout(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: COMBINES_KEY });
      qc.invalidateQueries({ queryKey: ACCOUNT_STATE_KEY });
      qc.invalidateQueries({ queryKey: COMBINE_EVENTS_KEY });
    },
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
  });
}
