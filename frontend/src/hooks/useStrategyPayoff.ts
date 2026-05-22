import { useQuery } from "@tanstack/react-query";
import { fetchStrategyPayoff } from "@/lib/api";
import type { StrategyType } from "@/types/bs";

export function useStrategyPayoff(symbol: string | null, strategy: StrategyType) {
  return useQuery({
    queryKey: ["bs", symbol, strategy],
    queryFn: () => fetchStrategyPayoff(symbol as string, strategy),
    enabled: !!symbol,
    refetchInterval: 30_000,
  });
}
