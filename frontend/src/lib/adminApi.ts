import { z } from "zod";

/**
 * Operator-console API client (workstream D1) — /api/admin/* plus the two
 * admin support-queue endpoints that live under /api/support/admin/*.
 *
 * Lives beside lib/api.ts rather than inside it per the P0-plan convention:
 * new domains get their own `lib/<domain>Api.ts` module and shared api.ts
 * stays untouched. The fetch conventions mirror api.ts exactly — session
 * cookies via `credentials: "include"`, FastAPI `detail` surfaced as the
 * Error message, HTTP status carried on the thrown error, zod-parsed
 * responses — because UI code downstream (toasts, error routing) assumes
 * those shapes everywhere.
 *
 * Backend gate errors follow the repo's machine-readable convention: the
 * detail string is "<snake_case_code>: <human message>" (e.g.
 * "invalid_transition: …", "last_admin: …"). `errorMessage()` strips the
 * code prefix for toasts; `errorCode()` extracts it for routing.
 *
 * Every response shape below mirrors a Pydantic response_model in
 * backend/routers/admin.py (or routers/support.py for the ticket queue) —
 * datetimes arrive as ISO strings.
 */

const API_BASE = "";

/** FastAPI error detail → readable string (mirrors api.ts detailToMessage:
 *  a plain HTTPException detail is a string; a pydantic 422 is a list of
 *  {loc, msg, type} objects). */
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

async function requestJson<S extends z.ZodTypeAny>(
  path: string,
  schema: S,
): Promise<z.infer<S>> {
  const res = await fetch(`${API_BASE}${path}`, { credentials: "include" });
  if (!res.ok) await throwHttpError(res);
  return schema.parse(await res.json());
}

async function mutateJson<S extends z.ZodTypeAny>(
  path: string,
  schema: S,
  init: RequestInit,
): Promise<z.infer<S>> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    ...init,
  });
  if (!res.ok) await throwHttpError(res);
  if (res.status === 204) return schema.parse(undefined);
  return schema.parse(await res.json());
}

/** Extract the machine-readable code from a backend gate error whose detail
 *  is "<snake_case_code>: <message>". Null when the error doesn't carry one. */
export function errorCode(err: unknown): string | null {
  const message = (err as Error)?.message;
  if (typeof message !== "string") return null;
  const m = /^([a-z][a-z0-9_]*):\s/.exec(message);
  return m ? m[1] : null;
}

/** The human half of a "code: message" gate error (the full message when
 *  no code prefix is present). */
export function errorMessage(err: unknown): string {
  const message = (err as Error)?.message || "Something went wrong";
  const m = /^[a-z][a-z0-9_]*:\s(.*)$/s.exec(message);
  return m ? m[1] : message;
}

// -- react-query keys ---------------------------------------------------------
// All admin data lives under the ["admin", …] prefix so a broad invalidation
// (e.g. after sign-in as a different operator) can nuke the whole console.

export const adminKeys = {
  all: ["admin"] as const,
  metrics: ["admin", "metrics"] as const,
  payouts: (state?: string) =>
    ["admin", "payouts", state ?? "actionable"] as const,
  payoutsPrefix: ["admin", "payouts"] as const,
  users: (q: string, page: number) => ["admin", "users", q, page] as const,
  usersPrefix: ["admin", "users"] as const,
  user: (id: number) => ["admin", "user", id] as const,
  platform: ["admin", "platform"] as const,
  jobs: ["admin", "jobs"] as const,
  actions: (targetType: string, targetId: string, page: number) =>
    ["admin", "actions", targetType, targetId, page] as const,
  actionsPrefix: ["admin", "actions"] as const,
  tickets: (status: string | undefined, q: string, page: number) =>
    ["admin", "tickets", status ?? "all", q, page] as const,
  ticketsPrefix: ["admin", "tickets"] as const,
};

// -- domain constants ----------------------------------------------------------

/** models/payout_request.PAYOUT_STATES, verbatim. */
export const PAYOUT_STATES = [
  "requested",
  "under_review",
  "approved",
  "denied",
  "held",
  "paid",
] as const;
export type PayoutState = (typeof PAYOUT_STATES)[number];

/** The states a reviewer can still act on — the queue's default view
 *  (GET /payouts with no state filter returns exactly these). */
export const ACTIONABLE_PAYOUT_STATES = [
  "requested",
  "under_review",
  "held",
] as const;

/** services/payout_desk.DENIAL_REASONS — the deny endpoint 422s on any
 *  reason_code outside this taxonomy. Order matters (menu order). */
export const DENIAL_REASON_OPTIONS = [
  { code: "rule_breach", label: "Trading rule breach" },
  { code: "prohibited_strategy", label: "Prohibited trading strategy" },
  { code: "news_window_abuse", label: "Trading around restricted news windows" },
  {
    code: "correlated_trading",
    label: "Correlated or coordinated trading across accounts",
  },
  { code: "sim_exploit", label: "Exploiting simulation or execution artifacts" },
  {
    code: "verification_incomplete",
    label: "Identity or tax verification incomplete",
  },
  { code: "chargeback_risk", label: "Payment dispute / chargeback risk" },
  { code: "other", label: "Other (see reviewer note)" },
] as const;
export type DenialReasonCode = (typeof DENIAL_REASON_OPTIONS)[number]["code"];

export const DENIAL_REASON_LABELS: Record<string, string> = Object.fromEntries(
  DENIAL_REASON_OPTIONS.map((o) => [o.code, o.label]),
);

/** services/platform_state.TRADING_MODES, verbatim. */
export const TRADING_MODES = ["normal", "close_only", "halted"] as const;
export type TradingMode = (typeof TRADING_MODES)[number];

export const TICKET_STATUSES = ["open", "replied", "closed"] as const;
export type TicketStatus = (typeof TICKET_STATUSES)[number];

/** The target_type values admin mutations write (services/admin_audit +
 *  routers/support.py) — drives the audit-log filter menu. */
export const AUDIT_TARGET_TYPES = [
  "user",
  "combine",
  "payment",
  "payout_request",
  "platform",
  "support_ticket",
] as const;

// -- users: search / detail -----------------------------------------------------

export const AdminUserItemSchema = z.object({
  id: z.number().int(),
  email: z.string(),
  display_name: z.string().nullable(),
  role: z.string(),
  suspended_at: z.string().nullable(),
  created_at: z.string(),
  reset_credits: z.number().int(),
  /** Combine counts by lifecycle status, e.g. {"active": 2, "archived": 1}. */
  combines: z.record(z.number().int()),
  /** "unverified" | "pending" | "verified" | "rejected" */
  kyc_status: z.string(),
});
export type AdminUserItem = z.infer<typeof AdminUserItemSchema>;

export const AdminUsersPageSchema = z.object({
  items: z.array(AdminUserItemSchema),
  total: z.number().int(),
  page: z.number().int(),
});
export type AdminUsersPage = z.infer<typeof AdminUsersPageSchema>;

export const ADMIN_USERS_PAGE_SIZE = 25;

export const fetchAdminUsers = (
  q: string,
  page: number,
  pageSize: number = ADMIN_USERS_PAGE_SIZE,
): Promise<AdminUsersPage> => {
  const p = new URLSearchParams();
  if (q) p.set("q", q);
  p.set("page", String(page));
  p.set("page_size", String(pageSize));
  return requestJson(`/api/admin/users?${p.toString()}`, AdminUsersPageSchema);
};

export const AdminCombineSchema = z.object({
  id: z.number().int(),
  tier: z.string(),
  name: z.string(),
  account_code: z.string(),
  status: z.string(),
  outcome: z.string(),
  hwm: z.number(),
  settled_hwm: z.number(),
  funded_at: z.string().nullable(),
  funded_activated_at: z.string().nullable(),
  funded_epoch_at: z.string().nullable(),
  eval_reset_at: z.string().nullable(),
  pricing_path: z.string(),
  profit_split: z.number(),
  paid_through: z.string().nullable(),
  cancel_at_period_end: z.boolean(),
  created_at: z.string(),
});
export type AdminCombine = z.infer<typeof AdminCombineSchema>;

export const AdminPaymentSchema = z.object({
  id: z.number().int(),
  combine_id: z.number().int().nullable(),
  tier: z.string(),
  amount: z.number(),
  status: z.string(),
  created_at: z.string(),
});
export type AdminPayment = z.infer<typeof AdminPaymentSchema>;

export const AdminEventSchema = z.object({
  id: z.number().int(),
  combine_id: z.number().int(),
  type: z.string(),
  message: z.string(),
  amount: z.number().nullable(),
  created_at: z.string(),
});
export type AdminEvent = z.infer<typeof AdminEventSchema>;

export const AdminTicketSummarySchema = z.object({
  id: z.number().int(),
  category: z.string(),
  subject: z.string(),
  status: z.string(),
  created_at: z.string(),
});
export type AdminTicketSummary = z.infer<typeof AdminTicketSummarySchema>;

export const AdminPayoutRequestSchema = z.object({
  id: z.number().int(),
  user_id: z.number().int(),
  combine_id: z.number().int(),
  amount: z.number(),
  state: z.string(),
  reason_code: z.string().nullable(),
  note: z.string().nullable(),
  reviewer_id: z.number().int().nullable(),
  requested_at: z.string(),
  decided_at: z.string().nullable(),
});
export type AdminPayoutRequest = z.infer<typeof AdminPayoutRequestSchema>;

export const AdminKycSchema = z.object({
  status: z.string(),
  provider: z.string(),
  reject_reason: z.string().nullable(),
  legal_name: z.string().nullable(),
  country: z.string().nullable(),
  submitted_at: z.string(),
  decided_at: z.string().nullable(),
});
export type AdminKyc = z.infer<typeof AdminKycSchema>;

export const AdminPayoutMethodSchema = z.object({
  id: z.number().int(),
  type: z.string(),
  label: z.string(),
  is_default: z.boolean(),
  created_at: z.string(),
});
export type AdminPayoutMethod = z.infer<typeof AdminPayoutMethodSchema>;

export const AdminUserDetailSchema = z.object({
  id: z.number().int(),
  email: z.string(),
  display_name: z.string().nullable(),
  role: z.string(),
  suspended_at: z.string().nullable(),
  created_at: z.string(),
  reset_credits: z.number().int(),
  active_combine_id: z.number().int().nullable(),
  combines: z.array(AdminCombineSchema),
  payments: z.array(AdminPaymentSchema),
  events: z.array(AdminEventSchema),
  tickets: z.array(AdminTicketSummarySchema),
  payout_requests: z.array(AdminPayoutRequestSchema),
  kyc: AdminKycSchema.nullable(),
  payout_methods: z.array(AdminPayoutMethodSchema),
});
export type AdminUserDetail = z.infer<typeof AdminUserDetailSchema>;

export const fetchAdminUserDetail = (id: number): Promise<AdminUserDetail> =>
  requestJson(`/api/admin/users/${id}`, AdminUserDetailSchema);

// -- users: mutations -------------------------------------------------------------

export const UserStateSchema = z.object({
  id: z.number().int(),
  role: z.string(),
  suspended_at: z.string().nullable(),
  reset_credits: z.number().int(),
});
export type UserState = z.infer<typeof UserStateSchema>;

/** Suspend a user — reason is REQUIRED (max 300 chars, non-empty). */
export const suspendUser = (id: number, reason: string): Promise<UserState> =>
  mutateJson(`/api/admin/users/${id}/suspend`, UserStateSchema, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });

export const unsuspendUser = (
  id: number,
  reason?: string,
): Promise<UserState> =>
  mutateJson(`/api/admin/users/${id}/unsuspend`, UserStateSchema, {
    method: "POST",
    body: JSON.stringify({ reason: reason || null }),
  });

export const promoteUser = (id: number, reason?: string): Promise<UserState> =>
  mutateJson(`/api/admin/users/${id}/promote`, UserStateSchema, {
    method: "POST",
    body: JSON.stringify({ reason: reason || null }),
  });

/** Demote an admin to trader. 422 on self-demotion, 409 "last_admin" when
 *  it would leave zero admins. */
export const demoteUser = (id: number, reason?: string): Promise<UserState> =>
  mutateJson(`/api/admin/users/${id}/demote`, UserStateSchema, {
    method: "POST",
    body: JSON.stringify({ reason: reason || null }),
  });

export const GrantCreditSchema = z.object({
  id: z.number().int(),
  reset_credits: z.number().int(),
  granted: z.number().int(),
});
export type GrantCredit = z.infer<typeof GrantCreditSchema>;

/** Grant free reset credits (clamped server-side to the pricing cap;
 *  409 "reset_credit_cap_reached" when already at it). Reason required. */
export const grantResetCredit = (
  id: number,
  count: number,
  reason: string,
): Promise<GrantCredit> =>
  mutateJson(`/api/admin/users/${id}/grant-reset-credit`, GrantCreditSchema, {
    method: "POST",
    body: JSON.stringify({ count, reason }),
  });

export const KycDecideSchema = z.object({
  user_id: z.number().int(),
  status: z.string(),
  reject_reason: z.string().nullable(),
  decided_at: z.string().nullable(),
});
export type KycDecide = z.infer<typeof KycDecideSchema>;

/** Human KYC decision on the user's pending verification. */
export const decideKyc = (
  id: number,
  approve: boolean,
  reason?: string,
): Promise<KycDecide> =>
  mutateJson(`/api/admin/users/${id}/kyc/decide`, KycDecideSchema, {
    method: "POST",
    body: JSON.stringify({ approve, reason: reason || null }),
  });

// -- combines: manual adjustment ---------------------------------------------------

export const COMBINE_ADJUST_ACTIONS = [
  "fail",
  "unfail",
  "extend_billing",
] as const;
export type CombineAdjustAction = (typeof COMBINE_ADJUST_ACTIONS)[number];

export const CombineAdjustResultSchema = z.object({
  id: z.number().int(),
  status: z.string(),
  outcome: z.string(),
  paid_through: z.string().nullable(),
});
export type CombineAdjustResult = z.infer<typeof CombineAdjustResultSchema>;

/** Manual combine adjustment. `extend_billing` requires days (1–90);
 *  reason always required. */
export const adjustCombine = (
  id: number,
  input: { action: CombineAdjustAction; reason: string; days?: number },
): Promise<CombineAdjustResult> =>
  mutateJson(`/api/admin/combines/${id}/adjust`, CombineAdjustResultSchema, {
    method: "POST",
    body: JSON.stringify({
      action: input.action,
      reason: input.reason,
      ...(input.days != null ? { days: input.days } : {}),
    }),
  });

// -- payments: refund ---------------------------------------------------------------

export const RefundResultSchema = z.object({
  id: z.number().int(),
  status: z.string(),
  combine_id: z.number().int().nullable(),
  combine_status: z.string().nullable(),
});
export type RefundResult = z.infer<typeof RefundResultSchema>;

/** Operator refund — archives the combine the payment bought (webhook
 *  semantics). Reason required. 409 when already refunded / not refundable. */
export const refundPayment = (
  id: number,
  reason: string,
): Promise<RefundResult> =>
  mutateJson(`/api/admin/payments/${id}/refund`, RefundResultSchema, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });

// -- payout review queue --------------------------------------------------------------

export const PayoutQueueItemSchema = AdminPayoutRequestSchema.extend({
  user_email: z.string(),
  tier: z.string(),
  account_code: z.string(),
  starting_balance: z.number(),
  balance: z.number(),
  total_approved_payouts: z.number(),
  days_since_funded: z.number().int().nullable(),
});
export type PayoutQueueItem = z.infer<typeof PayoutQueueItemSchema>;

export const PayoutQueueSchema = z.object({
  items: z.array(PayoutQueueItemSchema),
  total: z.number().int(),
});
export type PayoutQueue = z.infer<typeof PayoutQueueSchema>;

/** No state → the actionable queue (requested / under_review / held),
 *  oldest first (FIFO review order). */
export const fetchPayoutQueue = (state?: string): Promise<PayoutQueue> =>
  requestJson(
    `/api/admin/payouts${state ? `?state=${encodeURIComponent(state)}` : ""}`,
    PayoutQueueSchema,
  );

/** URL decision segments (backend maps "resume" → resume_review and
 *  "mark-paid" → mark_paid internally). */
export const PAYOUT_DECISIONS = [
  "approve",
  "deny",
  "hold",
  "resume",
  "mark-paid",
] as const;
export type PayoutDecision = (typeof PAYOUT_DECISIONS)[number];

/** One reviewer action. deny REQUIRES a valid reason_code (422 otherwise);
 *  a refused transition is a 409 "invalid_transition: …". */
export const decidePayout = (
  id: number,
  decision: PayoutDecision,
  body: { reason_code?: DenialReasonCode; note?: string } = {},
): Promise<AdminPayoutRequest> =>
  mutateJson(`/api/admin/payouts/${id}/${decision}`, AdminPayoutRequestSchema, {
    method: "POST",
    body: JSON.stringify({
      reason_code: body.reason_code ?? null,
      note: body.note || null,
    }),
  });

// -- platform kill switch ---------------------------------------------------------------

export const PlatformStateSchema = z.object({
  trading_mode: z.string(),
  banned_symbols: z.array(z.string()),
  zero_dte_universe: z.array(z.string()),
  enforce_tradeable_universe: z.boolean(),
});
export type PlatformState = z.infer<typeof PlatformStateSchema>;

export const fetchPlatform = (): Promise<PlatformState> =>
  requestJson("/api/admin/platform", PlatformStateSchema);

/** PUT — either field alone is fine; both omitted is a 400. */
export const updatePlatform = (input: {
  trading_mode?: TradingMode;
  banned_symbols?: string[];
}): Promise<PlatformState> =>
  mutateJson("/api/admin/platform", PlatformStateSchema, {
    method: "PUT",
    body: JSON.stringify(input),
  });

// -- metrics ------------------------------------------------------------------------------

export const TierCombineCountsSchema = z.object({
  by_status: z.record(z.number().int()),
  by_outcome: z.record(z.number().int()),
});
export type TierCombineCounts = z.infer<typeof TierCombineCountsSchema>;

export const AdminMetricsSchema = z.object({
  mrr: z.number(),
  combines: z.record(TierCombineCountsSchema),
  /** funded / terminal per tier; null = no terminal outcomes yet. */
  pass_rate: z.record(z.number().nullable()),
  payout_liability: z.record(z.number()),
  users_total: z.number().int(),
  users_last_30d: z.number().int(),
  tickets_open: z.number().int(),
});
export type AdminMetrics = z.infer<typeof AdminMetricsSchema>;

export const fetchAdminMetrics = (): Promise<AdminMetrics> =>
  requestJson("/api/admin/metrics", AdminMetricsSchema);

// -- jobs health ----------------------------------------------------------------------------

export const JobHealthSchema = z.object({
  name: z.string(),
  status: z.string(),
  duration_s: z.number(),
  error: z.string().nullable(),
  started_at: z.string(),
  cadence_s: z.number().int().nullable(),
  stale: z.boolean(),
});
export type JobHealth = z.infer<typeof JobHealthSchema>;

export const fetchJobsHealth = (): Promise<JobHealth[]> =>
  requestJson("/api/admin/jobs", z.array(JobHealthSchema));

// -- audit log ------------------------------------------------------------------------------

export const AdminActionSchema = z.object({
  id: z.number().int(),
  actor_id: z.number().int(),
  action: z.string(),
  target_type: z.string(),
  target_id: z.number().int().nullable(),
  before: z.record(z.unknown()),
  after: z.record(z.unknown()),
  reason: z.string().nullable(),
  created_at: z.string(),
});
export type AdminAction = z.infer<typeof AdminActionSchema>;

export const AdminActionsPageSchema = z.object({
  items: z.array(AdminActionSchema),
  total: z.number().int(),
  page: z.number().int(),
});
export type AdminActionsPage = z.infer<typeof AdminActionsPageSchema>;

export const ADMIN_ACTIONS_PAGE_SIZE = 50;

export const fetchAdminActions = (filters: {
  targetType?: string;
  targetId?: number;
  page?: number;
  pageSize?: number;
}): Promise<AdminActionsPage> => {
  const p = new URLSearchParams();
  if (filters.targetType) p.set("target_type", filters.targetType);
  if (filters.targetId != null) p.set("target_id", String(filters.targetId));
  p.set("page", String(filters.page ?? 1));
  p.set("page_size", String(filters.pageSize ?? ADMIN_ACTIONS_PAGE_SIZE));
  return requestJson(`/api/admin/actions?${p.toString()}`, AdminActionsPageSchema);
};

// -- support queue (routers/support.py — /api/support/admin/*) --------------------------------

export const AdminTicketSchema = z.object({
  id: z.number().int(),
  category: z.string(),
  subject: z.string(),
  body: z.string(),
  /** Auto-attached active-combine context: {combine_id, tier, status} or {}. */
  context: z.record(z.unknown()),
  status: z.string(),
  admin_note: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
  user_id: z.number().int(),
  user_email: z.string(),
});
export type AdminTicket = z.infer<typeof AdminTicketSchema>;

export const AdminTicketsResponseSchema = z.object({
  tickets: z.array(AdminTicketSchema),
  total: z.number().int(),
  page: z.number().int(),
});
export type AdminTicketsPage = z.infer<typeof AdminTicketsResponseSchema>;

export const ADMIN_TICKETS_PAGE_SIZE = 25;

export const fetchAdminTickets = (
  status: TicketStatus | undefined,
  q: string,
  page: number,
  pageSize: number = ADMIN_TICKETS_PAGE_SIZE,
): Promise<AdminTicketsPage> => {
  const p = new URLSearchParams();
  if (status) p.set("status", status);
  if (q) p.set("q", q);
  p.set("page", String(page));
  p.set("page_size", String(pageSize));
  return requestJson(
    `/api/support/admin/tickets?${p.toString()}`,
    AdminTicketsResponseSchema,
  );
};

/** Work a ticket: set status and/or the admin reply note. A set/changed
 *  non-empty note also notifies the ticket's owner in-app. */
export const updateAdminTicket = (
  id: number,
  input: { status?: TicketStatus; admin_note?: string },
): Promise<AdminTicket> =>
  mutateJson(`/api/support/admin/tickets/${id}`, AdminTicketSchema, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
