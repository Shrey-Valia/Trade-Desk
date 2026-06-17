import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { fetchContractPreview } from "@/lib/api";
import { useTradeTicket } from "@/stores/tradeTicket";

/**
 * Pre-trade payoff + greeks for the currently-selected chain contract,
 * powering the trade-ticket's contract-detail panel. Keyed on the
 * selection + quantity; disabled when nothing is selected. The backend
 * resolves indicative pricing, so this works with the market closed.
 */
export function useContractPreview() {
  const selection = useTradeTicket((s) => s.selection);
  const contracts = useTradeTicket((s) => s.contracts);

  return useQuery({
    queryKey: [
      "contract-preview",
      selection?.symbol ?? null,
      selection?.kind ?? null,
      selection?.side ?? null,
      selection?.strike ?? null,
      contracts,
    ],
    queryFn: () =>
      fetchContractPreview({
        symbol: selection!.symbol,
        kind: selection!.kind,
        side: selection!.side,
        strike: selection!.strike,
        contracts,
      }),
    enabled: !!selection,
    staleTime: 10_000,
    retry: 1,
    placeholderData: keepPreviousData,
  });
}
