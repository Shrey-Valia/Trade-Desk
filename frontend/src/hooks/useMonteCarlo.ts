import { useQuery } from "@tanstack/react-query";
import { fetchMonteCarlo } from "@/lib/api";

export function useMonteCarlo(symbol: string | null) {
  return useQuery({
    queryKey: ["mc", symbol],
    queryFn: () => fetchMonteCarlo(symbol as string),
    enabled: !!symbol,
    // 30s — matches the backend's MC cache TTL. Inside that window every
    // poll hits the server cache and gets the identical sample paths.
    refetchInterval: 30_000,
  });
}
