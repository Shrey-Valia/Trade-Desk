import { useMutation, useQueryClient } from "@tanstack/react-query";

import { openZeroDteMultiLeg } from "@/lib/api";
import { useActivePosition } from "@/stores/activePosition";
import { toast } from "@/stores/toast";
import type { OpenMultiLegInput } from "@/types/zerodte";

/**
 * WS5 — multi-leg strategy builder open. Mirrors useOpenZeroDteStraddle:
 * on success invalidate the trades + account queries and set the new
 * position active so it draws on the chart immediately.
 */
export function useOpenZeroDteMultiLeg() {
  const queryClient = useQueryClient();
  const setActiveTradeId = useActivePosition((s) => s.setTradeId);
  return useMutation({
    mutationFn: (input: OpenMultiLegInput) => openZeroDteMultiLeg(input),
    onSuccess: (trade) => {
      queryClient.invalidateQueries({ queryKey: ["journal", "trades"] });
      queryClient.invalidateQueries({ queryKey: ["account", "state"] });
      setActiveTradeId(trade.id);
      toast.success(
        `${trade.strategy.replace(/_/g, " ")} opened — ${trade.symbol}.`,
      );
    },
    onError: (e) =>
      toast.error((e as Error)?.message || "Could not open structure"),
  });
}
