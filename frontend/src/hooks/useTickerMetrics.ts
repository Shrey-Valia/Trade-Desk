import { useQuery } from "@tanstack/react-query";
import { fetchTickerMetrics } from "@/lib/api";

export function useTickerMetrics(symbol: string | null) {
  return useQuery({
    queryKey: ["ticker", "metrics", symbol],
    queryFn: () => fetchTickerMetrics(symbol as string),
    enabled: !!symbol,
    refetchInterval: 5_000,
  });
}
