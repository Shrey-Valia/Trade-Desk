import { z } from "zod";

/**
 * Legal-consent + support + account-recovery API client (workstream D2).
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
 * "consent_required: …", "agreement_required: …", "invalid_token: …").
 * `errorCode()` extracts the prefix so pages can route on it.
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
  // 204s (forgot/reset) have no body to parse.
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

// -- legal consent ------------------------------------------------------------

export const DocStatusSchema = z.object({
  /** Highest version the user has ever accepted; null = never. */
  accepted_version: z.number().int().nullable(),
  current_version: z.number().int(),
  /** Whether the acceptance satisfies today's version. */
  current: z.boolean(),
});
export type DocStatus = z.infer<typeof DocStatusSchema>;

/** {doc_key: status} for tos / privacy / refund / risk / funded_agreement. */
export const LegalStatusSchema = z.record(DocStatusSchema);
export type LegalStatus = z.infer<typeof LegalStatusSchema>;

/** Shared react-query key so consent state stays coherent across the
 *  signup, purchase, and activation surfaces. */
export const LEGAL_IDENTITY_KEY = ["legal", "identity"] as const;

/**
 * Who the public legal documents name as the counterparty. Operator-supplied
 * (backend settings), so it cannot live in source.
 *
 * Every field may be blank, and blank means blank: the pages omit the clause
 * and fall back to the in-app Support page rather than printing a
 * plausible-looking address. `configured` is the single flag to gate on.
 */
export const LegalIdentitySchema = z.object({
  entity_name: z.string(),
  jurisdiction: z.string(),
  contact_email: z.string(),
  contact_address: z.string(),
  configured: z.boolean(),
});
export type LegalIdentity = z.infer<typeof LegalIdentitySchema>;

export const fetchLegalIdentity = (): Promise<LegalIdentity> =>
  requestJson("/api/legal/identity", LegalIdentitySchema);

export const LEGAL_STATUS_KEY = ["legal", "status"] as const;

export const fetchLegalStatus = (): Promise<LegalStatus> =>
  requestJson("/api/legal/status", LegalStatusSchema);

/** Checkbox acceptance of documents at their CURRENT versions (idempotent).
 *  Returns the refreshed status map. */
export const acceptDocuments = (docKeys: string[]): Promise<LegalStatus> =>
  mutateJson("/api/legal/accept", LegalStatusSchema, {
    method: "POST",
    body: JSON.stringify({ doc_keys: docKeys }),
  });

/** Typed-name e-sign of the funded-trader agreement — the activation gate
 *  requires a SIGNED acceptance, not a checkbox one. */
export const signFundedAgreement = (typedName: string): Promise<LegalStatus> =>
  mutateJson("/api/legal/sign-funded-agreement", LegalStatusSchema, {
    method: "POST",
    body: JSON.stringify({ typed_name: typedName }),
  });

/** True when the purchase gate (tos + risk at current versions) is NOT yet
 *  satisfied — the caller should surface the consent checkbox. */
export function needsPurchaseConsent(status: LegalStatus | undefined): boolean {
  if (!status) return false; // unknown yet — the 403 fallback still catches it
  return !(status.tos?.current && status.risk?.current);
}

// -- account recovery ---------------------------------------------------------

/** Always 204 — identical for known and unknown emails (no enumeration). */
export const forgotPassword = (email: string): Promise<void> =>
  mutateJson("/api/auth/forgot", z.void(), {
    method: "POST",
    body: JSON.stringify({ email }),
  });

/** 204 on success (all sessions revoked); 400 "invalid_token: …" when the
 *  link is invalid, expired, or already used. */
export const resetPassword = (
  token: string,
  newPassword: string,
): Promise<void> =>
  mutateJson("/api/auth/reset", z.void(), {
    method: "POST",
    body: JSON.stringify({ token, new_password: newPassword }),
  });

// -- support tickets ----------------------------------------------------------

export const TICKET_CATEGORIES = [
  "rule_dispute",
  "billing",
  "payout",
  "bug",
  "other",
] as const;
export type TicketCategory = (typeof TICKET_CATEGORIES)[number];

export const TICKET_CATEGORY_LABELS: Record<TicketCategory, string> = {
  rule_dispute: "Rule dispute",
  billing: "Billing",
  payout: "Payout",
  bug: "Bug report",
  other: "Other",
};

export const SupportTicketSchema = z.object({
  id: z.number().int(),
  category: z.string(),
  subject: z.string(),
  body: z.string(),
  /** Auto-attached active-combine context: {combine_id, tier, status} or {}. */
  context: z.record(z.unknown()),
  status: z.string(), // open | replied | closed
  admin_note: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type SupportTicket = z.infer<typeof SupportTicketSchema>;

const TicketsResponseSchema = z.object({
  tickets: z.array(SupportTicketSchema),
});

export const SUPPORT_TICKETS_KEY = ["support", "tickets"] as const;

export interface TicketInput {
  category: TicketCategory;
  subject: string;
  body: string;
}

export const createSupportTicket = (input: TicketInput): Promise<SupportTicket> =>
  mutateJson("/api/support/tickets", SupportTicketSchema, {
    method: "POST",
    body: JSON.stringify(input),
  });

export const fetchSupportTickets = (): Promise<SupportTicket[]> =>
  requestJson("/api/support/tickets", TicketsResponseSchema).then(
    (r) => r.tickets,
  );
