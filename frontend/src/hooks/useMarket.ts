import { useQuery } from "@tanstack/react-query";
import { fetchMarketIndices, fetchMarketStatus } from "@/lib/api";

export function useMarketStatus() {
  return useQuery({
    queryKey: ["market", "status"],
    queryFn: fetchMarketStatus,
    refetchInterval: 60_000, // 1min — session boundaries don't move intraday
  });
}

export function useMarketIndices() {
  return useQuery({
    queryKey: ["market", "indices"],
    queryFn: fetchMarketIndices,
    refetchInterval: 5_000, // 5s during/after market hours
  });
}
