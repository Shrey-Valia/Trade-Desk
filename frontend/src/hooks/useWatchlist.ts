import { useQuery } from "@tanstack/react-query";
import { fetchWatchlist } from "@/lib/api";

export function useWatchlist() {
  return useQuery({
    queryKey: ["watchlist"],
    queryFn: fetchWatchlist,
    refetchInterval: 30_000,
  });
}
