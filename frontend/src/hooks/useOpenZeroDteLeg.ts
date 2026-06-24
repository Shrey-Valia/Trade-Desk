import { useMutation, useQueryClient } from "@tanstack/react-query";

import { openZeroDteLeg } from "@/lib/zerodteOpen";
import { useActivePosition } from "@/stores/activePosition";
import { toast } from "@/stores/toast";

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
      // Account state polls every 5s; invalidating here makes the
      // header BAL/MLL/RP&L update immediately instead of lagging.
      queryClient.invalidateQueries({ queryKey: ["account", "state"] });
      if (trade.status === "working") {
        // A resting limit/stop order — not yet a position, so don't make
        // it the active chart position; it shows in the working-orders list.
        const kind =
          trade.order_type === "stop"
            ? "Stop"
            : trade.order_type === "stop_limit"
              ? "Stop-limit"
              : "Limit";
        toast.success(`${kind} order placed — ${trade.symbol}.`);
      } else {
        setActiveTradeId(trade.id);
        toast.success(`Position opened — ${trade.symbol}.`);
      }
    },
    onError: (e) => toast.error((e as Error)?.message || "Could not open position"),
  });
}
