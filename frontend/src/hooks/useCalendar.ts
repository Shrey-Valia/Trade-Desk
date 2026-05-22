import { useQuery } from "@tanstack/react-query";
import { fetchCalendar } from "@/lib/api";

export function useCalendar() {
  return useQuery({
    queryKey: ["calendar"],
    queryFn: fetchCalendar,
    refetchInterval: 60 * 60 * 1000, // 1h — events don't move intraday
  });
}
