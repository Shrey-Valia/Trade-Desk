import { z } from "zod";

/**
 * In-app notification-center API client (workstream D3) — the header bell.
 *
 * Lives beside lib/api.ts rather than inside it per the P0-plan convention:
 * new domains get their own `lib/<domain>Api.ts` module and shared api.ts
 * stays untouched. Fetch conventions mirror api.ts — session cookies via
 * `credentials: "include"`, FastAPI `detail` surfaced as the Error message,
 * HTTP status carried on the thrown error, zod-parsed responses.
 */

const API_BASE = "";

/** FastAPI error detail → readable string (mirrors api.ts detailToMessage). */
function detailToMessage(detail: unknown): string | null {
  if (detail == null) return null;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((e) => {
        if (e && typeof e === "object" && "msg" in e) {
          const loc = Array.isArray((e as { loc?: unknown[] }).loc)
            ? (e as { loc: unknown[] }).loc.slice(1).join(".")
            : "";
          const msg = String((e as { msg: unknown }).msg);
          return loc ? `${loc}: ${msg}` : msg;
        }
        return typeof e === "string" ? e : null;
      })
      .filter(Boolean);
    return parts.length ? parts.join("; ") : null;
  }
  return null;
}

async function throwHttpError(res: Response): Promise<never> {
  let detail = `${res.status} ${res.statusText}`;
  try {
    const body = await res.json();
    const msg = detailToMessage((body as { detail?: unknown })?.detail);
    if (msg) detail = msg;
  } catch {
    /* non-JSON body */
  }
  const err = new Error(detail) as Error & { status?: number };
  err.status = res.status;
  throw err;
}

export const NotificationSchema = z.object({
  id: z.number().int(),
  /** Lifecycle event type the notifier mapped — funded, failed,
   *  payout_requested / payout_approved / payout_denied, renewal, … */
  kind: z.string(),
  title: z.string(),
  body: z.string(),
  read_at: z.string().nullable(),
  created_at: z.string(),
});
export type Notification = z.infer<typeof NotificationSchema>;

export const NotificationsOutSchema = z.object({
  items: z.array(NotificationSchema),
  /** TOTAL unread count — the badge number (counts past the 50 shown). */
  unread: z.number().int(),
});
export type NotificationsOut = z.infer<typeof NotificationsOutSchema>;

export const NOTIFICATIONS_KEY = ["notifications"] as const;

/** The caller's newest 50 notifications + total unread count. */
export const fetchNotifications = (): Promise<NotificationsOut> =>
  fetch(`${API_BASE}/api/notifications`, { credentials: "include" }).then(
    async (res) => {
      if (!res.ok) await throwHttpError(res);
      return NotificationsOutSchema.parse(await res.json());
    },
  );

/** Mark the listed ids read — or ALL unread when `ids` is omitted.
 *  Idempotent server-side; resolves on the 204. */
export const markNotificationsRead = async (
  ids?: number[],
): Promise<void> => {
  const res = await fetch(`${API_BASE}/api/notifications/read`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(ids ? { ids } : {}),
  });
  if (!res.ok) await throwHttpError(res);
};

/** Payout-lifecycle notifications deep-link to /payouts from the bell. */
export function isPayoutNotification(n: Notification): boolean {
  return n.kind.startsWith("payout");
}
