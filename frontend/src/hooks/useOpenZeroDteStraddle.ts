import { useMutation, useQueryClient } from "@tanstack/react-query";

import { openZeroDteStraddle } from "@/lib/api";
import { useActivePosition } from "@/stores/activePosition";
import { toast } from "@/stores/toast";

/**
 * Mutation hook for the "0DTE STRADDLE" quick-entry button.
 *
 * On success:
 *   - Invalidates the trades query so TradeList / JournalPanel pick
 *     up the new position immediately.
 *   - Sets the new trade as the active position so the chart overlay
 *     + scrubber render against it without any extra click.
 */
export function useOpenZeroDteStraddle() {
  const queryClient = useQueryClient();
  const setActiveTradeId = useActivePosition((s) => s.setTradeId);
  return useMutation({
    mutationFn: ({
      symbol,
      action = "buy",
      contracts,
    }: {
      symbol: string;
      action?: "buy" | "sell";
      contracts?: number;
    }) => openZeroDteStraddle(symbol, action, contracts ?? 1),
    onSuccess: (trade) => {
      // useTrades keys queries as ["journal","trades",filters]. An
      // invalidation key of ["trades"] silently no-matches (wrong prefix)
      // — that's the bug that made successful opens look stuck. Match
      // the prefix and the open-positions list refreshes immediately.
      queryClient.invalidateQueries({ queryKey: ["journal", "trades"] });
      // Account state polls every 5s; invalidate so the header
      // BAL/MLL/RP&L update immediately.
      queryClient.invalidateQueries({ queryKey: ["account", "state"] });
      setActiveTradeId(trade.id);
      toast.success(`Straddle opened — ${trade.symbol}.`);
    },
    onError: (e) => toast.error((e as Error)?.message || "Could not open straddle"),
  });
}
