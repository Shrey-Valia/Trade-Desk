import { useMutation, useQueryClient } from "@tanstack/react-query";

import { openZeroDteLeg } from "@/lib/zerodteOpen";
import { useActivePosition } from "@/stores/activePosition";

/**
 * Click-a-strike-cell mutation. On success, invalidates trades and
 * sets the new position as active so it draws on the chart immediately.
 */
export function useOpenZeroDteLeg() {
  const queryClient = useQueryClient();
  const setActiveTradeId = useActivePosition((s) => s.setTradeId);
  return useMutation({
    mutationFn: openZeroDteLeg,
    onSuccess: (trade) => {
      queryClient.invalidateQueries({ queryKey: ["journal", "trades"] });
      setActiveTradeId(trade.id);
    },
  });
}
