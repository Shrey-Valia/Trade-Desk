import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  activateAccount,
  activateCombine,
  archiveCombine,
  cancelCombine,
  fetchCombineEvents,
  fetchCombines,
  fetchPaymentsHistory,
  purchaseCombine,
  renameCombine,
  requestPayout,
  resetCombine,
  resumeCombine,
  updateCopyConfig,
} from "@/lib/api";
import { errorCode, errorMessage } from "@/lib/legalApi";
import { useActivePosition } from "@/stores/activePosition";
import { toast } from "@/stores/toast";
import type { CopyConfigInput, PurchaseInput } from "@/types/combine";

// Backend gate errors arrive as "snake_case_code: human message" — strip the
// machine code before it reaches a toast (errorMessage does exactly that).
const errMsg = (e: unknown) => errorMessage(e) || "Something went wrong";

// Gate codes the calling UI already routes on (opening the KYC step, the
// funded-agreement modal, the consent checkbox). The hook-level toast would
// duplicate that recovery UI with a raw error — skip it for these codes.
const UI_ROUTED_CODES = new Set([
  "kyc_required",
  "tax_profile_required",
  "payout_method_required",
  "agreement_required",
  "consent_required",
]);

const toastUnlessRouted = (e: unknown) => {
  const code = errorCode(e);
  if (code && UI_ROUTED_CODES.has(code)) return;
  toast.error(errMsg(e));
};

export const COMBINES_KEY = ["combines"] as const;
export const COMBINE_EVENTS_KEY = ["combines", "events"] as const;
export const PAYMENTS_HISTORY_KEY = ["payments", "history"] as const;
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
    // consent_required routes to the inline checkbox on NewCombinePage.
    onError: toastUnlessRouted,
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
    // consent_required (ToS version bump) routes to the consent UI.
    onError: toastUnlessRouted,
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
    // kyc/tax/method gate codes route to the readiness steps on PayoutsPage.
    onError: toastUnlessRouted,
  });
}

/** Charge history for the Settings billing tab. Retry off: a 404 (endpoint
 *  still rolling out) or auth failure should degrade to the tab's empty
 *  state, not spin. */
export function usePaymentsHistory() {
  return useQuery({
    queryKey: PAYMENTS_HISTORY_KEY,
    queryFn: fetchPaymentsHistory,
    staleTime: 30_000,
    retry: false,
  });
}

const periodEndText = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      })
    : "the period end";

/** Cancel at period end — the combine stays tradeable until paid_through,
 *  then archives and the monthly charge stops. Reversible via resume. */
export function useCancelCombine() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => cancelCombine(id),
    onSuccess: (combine) => {
      qc.invalidateQueries({ queryKey: COMBINES_KEY });
      qc.invalidateQueries({ queryKey: ACCOUNT_STATE_KEY });
      toast.info(
        `${combine.name} cancelled — tradeable until ${periodEndText(combine.paid_through)}, then it archives and billing stops.`,
      );
    },
    onError: (e) => toast.error(errMsg(e)),
  });
}

/** Undo a pending cancel — the subscription renews at the period end. */
export function useResumeCombine() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => resumeCombine(id),
    onSuccess: (combine) => {
      qc.invalidateQueries({ queryKey: COMBINES_KEY });
      qc.invalidateQueries({ queryKey: ACCOUNT_STATE_KEY });
      toast.success(`${combine.name} resumed — billing continues at the next renewal.`);
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
    // agreement_required routes to the FundedAgreementModal.
    onError: toastUnlessRouted,
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
