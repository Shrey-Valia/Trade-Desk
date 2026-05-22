import { useQuery } from "@tanstack/react-query";
import { fetchModelSignals } from "@/lib/api";

export function useModelSignals(symbol: string | null) {
  return useQuery({
    queryKey: ["models", symbol],
    queryFn: () => fetchModelSignals(symbol as string),
    enabled: !!symbol,
    // Inference is fast, but features cached 1h on backend; 5min refetch
    // is plenty and matches the model retrain cadence we'll set up later.
    refetchInterval: 5 * 60 * 1000,
  });
}
