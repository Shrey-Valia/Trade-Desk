import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  cancelOrder,
  createTrade,
  deleteTrade,
  fetchTrades,
  setBrackets,
  updateTrade,
  type TradeListFilters,
} from "@/lib/api";
import { toast } from "@/stores/toast";
import type { TradeInput, TradeUpdateInput } from "@/types/journal";

const TRADES_KEY = ["journal", "trades"] as const;

export function useTrades(
  filters: TradeListFilters = {},
  options: { refetchInterval?: number | false } = {},
) {
  return useQuery({
    queryKey: [...TRADES_KEY, filters],
    queryFn: () => fetchTrades(filters),
    staleTime: 10_000,
    // Off by default — only the live feed opts into polling. Because the
    // ["journal","trades",{}] key is shared, the interval applies to that
    // cache entry whenever the feed is mounted (no duplicate requests).
    refetchInterval: options.refetchInterval,
  });
}

export function useCreateTrade() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: TradeInput) => createTrade(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: TRADES_KEY }),
    onError: (e) => toast.error((e as Error)?.message || "Could not log trade"),
  });
}

export function useUpdateTrade() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { id: number; patch: TradeUpdateInput }) =>
      updateTrade(args.id, args.patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: TRADES_KEY }),
    onError: (e) => toast.error((e as Error)?.message || "Could not save changes"),
  });
}

export function useDeleteTrade() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => deleteTrade(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: TRADES_KEY }),
    onError: (e) => toast.error((e as Error)?.message || "Could not delete trade"),
  });
}

/** Cancel a working (unfilled) limit/stop order. */
export function useCancelOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => cancelOrder(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: TRADES_KEY });
      toast.info("Order cancelled.");
    },
    onError: (e) => toast.error((e as Error)?.message || "Could not cancel order"),
  });
}

/** Set/clear the SL/TP brackets on a trade (the draggable chart lines). */
export function useSetBrackets() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { id: number; stop_loss: number | null; take_profit: number | null }) =>
      setBrackets(args.id, { stop_loss: args.stop_loss, take_profit: args.take_profit }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: TRADES_KEY });
      qc.invalidateQueries({ queryKey: ["account", "state"] });
    },
    onError: (e) => toast.error((e as Error)?.message || "Could not update brackets"),
  });
}
