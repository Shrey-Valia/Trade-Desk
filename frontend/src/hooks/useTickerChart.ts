import { useQuery } from "@tanstack/react-query";
import { fetchTickerChart } from "@/lib/api";
import type { ChartTimeframe } from "@/types/chart";

export function useTickerChart(symbol: string | null, timeframe: ChartTimeframe) {
  return useQuery({
    queryKey: ["ticker", "chart", symbol, timeframe],
    queryFn: () => fetchTickerChart(symbol as string, timeframe),
    enabled: !!symbol,
    refetchInterval: 5_000,
  });
}
