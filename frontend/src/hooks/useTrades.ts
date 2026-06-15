import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createTrade,
  deleteTrade,
  fetchTrades,
  updateTrade,
  type TradeListFilters,
} from "@/lib/api";
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
  });
}

export function useUpdateTrade() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { id: number; patch: TradeUpdateInput }) =>
      updateTrade(args.id, args.patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: TRADES_KEY }),
  });
}

export function useDeleteTrade() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => deleteTrade(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: TRADES_KEY }),
  });
}
