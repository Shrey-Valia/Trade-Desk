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
        // A resting limit/stop order — not yet a position, so don't make it
        // the active chart position; it shows in the Pending Orders list.
        // Use a warning toast (amber) with explicit "WORKING / not filled"
        // wording so it never reads as an immediate fill, and a longer TTL.
        const kind = trade.order_type === "stop" ? "Stop" : "Limit";
        const at = trade.limit_price != null ? ` @ $${trade.limit_price.toFixed(2)}` : "";
        toast.warning(
          `${trade.symbol} ${kind} order WORKING${at} — NOT filled yet. It rests until the mark crosses the trigger (see Pending Orders).`,
          8_000,
        );
      } else {
        setActiveTradeId(trade.id);
        toast.success(`Position opened — ${trade.symbol}.`);
      }
    },
    onError: (e) => toast.error((e as Error)?.message || "Could not open position"),
  });
}
