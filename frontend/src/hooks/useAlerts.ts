import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createAlert,
  deleteAlert,
  evaluateAlerts,
  fetchAlerts,
  rearmAlert,
} from "@/lib/api";
import { toast } from "@/stores/toast";
import type { Alert, AlertInput } from "@/types/alert";

const ALERTS_KEY = ["alerts"] as const;

/** List the user's alerts. Polls on the same ~15s cadence as the live feed
 *  so a server-side trip (or a fill alert) surfaces without a manual refetch. */
export function useAlerts() {
  return useQuery({
    queryKey: ALERTS_KEY,
    queryFn: fetchAlerts,
    staleTime: 10_000,
  });
}

export function useCreateAlert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: AlertInput) => createAlert(input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ALERTS_KEY });
      toast.success("Alert set.");
    },
    onError: (e) => toast.error((e as Error)?.message || "Could not create alert"),
  });
}

export function useDeleteAlert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => deleteAlert(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ALERTS_KEY }),
    onError: (e) => toast.error((e as Error)?.message || "Could not delete alert"),
  });
}

export function useRearmAlert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => rearmAlert(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ALERTS_KEY }),
    onError: (e) => toast.error((e as Error)?.message || "Could not re-arm alert"),
  });
}

/**
 * Price-alert evaluator (WS6) — the minimal wiring that makes alerts fire.
 *
 * Mounted once in the authed shell. On the quote-poll cadence it asks the
 * server to evaluate active price alerts against live quotes; any that just
 * tripped come back and we raise a sticky toast (one per alert, de-duped by
 * id so a slow re-poll can't double-announce). The alert list is invalidated
 * so the bell badge + alerts panel reflect the new "triggered" status.
 *
 * Evaluation is server-authoritative (it persists the trip), so this hook
 * stays a thin driver — no client-side price math that could drift from the
 * backend's quote source.
 */
export function useAlertEvaluator(enabled: boolean = true) {
  const qc = useQueryClient();
  const { data } = useAlerts();
  const firedRef = useRef<Set<number>>(new Set());

  const hasActivePrice = (data?.alerts ?? []).some(
    (a) => a.status === "active" && a.kind === "price",
  );

  useEffect(() => {
    if (!enabled || !hasActivePrice) return;
    let cancelled = false;

    async function tick() {
      try {
        const res = await evaluateAlerts();
        if (cancelled || res.triggered.length === 0) return;
        for (const a of res.triggered) {
          if (firedRef.current.has(a.id)) continue;
          firedRef.current.add(a.id);
          toast.warning(alertFiredMessage(a), 0); // sticky — user dismisses
        }
        qc.invalidateQueries({ queryKey: ALERTS_KEY });
      } catch {
        // Degraded market data — skip this pass; the next one retries.
      }
    }

    // Fire once immediately, then on the 15s quote cadence.
    tick();
    const id = window.setInterval(tick, 15_000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [enabled, hasActivePrice, qc]);
}

function alertFiredMessage(a: Alert): string {
  const dir = a.direction === "below" ? "fell below" : "rose above";
  const lvl = a.threshold != null ? `$${a.threshold}` : "level";
  const note = a.note ? ` — ${a.note}` : "";
  return `Alert: ${a.symbol} ${dir} ${lvl}${note}`;
}
