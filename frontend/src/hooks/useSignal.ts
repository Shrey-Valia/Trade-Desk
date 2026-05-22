import { useQuery } from "@tanstack/react-query";
import { fetchSignal } from "@/lib/api";

export function useSignal(symbol: string | null) {
  return useQuery({
    queryKey: ["signal", symbol],
    queryFn: () => fetchSignal(symbol as string),
    enabled: !!symbol,
    // Composer cache is 60s on the backend; mirror that here so the UI
    // doesn't burn requests every focus.
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}
