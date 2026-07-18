import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  NOTIFICATIONS_KEY,
  fetchNotifications,
  markNotificationsRead,
} from "@/lib/notificationsApi";
import { toast } from "@/stores/toast";

/**
 * Notification-center queries (workstream D3).
 *
 * The list polls on a ~30s cadence — notifications are written by the
 * scheduler's event tail (jobs/notify_events), so anything faster just
 * hammers the API between job runs. staleTime mirrors the header's other
 * slow feeds (useCombineEvents) so a remount inside the window reuses the
 * cache instead of refetching.
 */
export function useNotifications() {
  return useQuery({
    queryKey: NOTIFICATIONS_KEY,
    queryFn: fetchNotifications,
    refetchInterval: 30_000,
    staleTime: 15_000,
  });
}

/** Mark ids read (or ALL unread when called with no ids), then refresh the
 *  list so the badge and unread dots settle in one round trip. */
export function useMarkNotificationsRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ids?: number[]) => markNotificationsRead(ids),
    onSuccess: () => qc.invalidateQueries({ queryKey: NOTIFICATIONS_KEY }),
    onError: (e) =>
      toast.error((e as Error)?.message || "Could not mark notifications read"),
  });
}
