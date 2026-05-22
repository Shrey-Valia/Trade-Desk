import { useQuery } from "@tanstack/react-query";
import { fetchTickerDetail } from "@/lib/api";

export function useTickerDetail(symbol: string | null) {
  return useQuery({
    queryKey: ["ticker", "detail", symbol],
    queryFn: () => fetchTickerDetail(symbol as string),
    enabled: !!symbol,
    refetchInterval: 5_000,
  });
}
