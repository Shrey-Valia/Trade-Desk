import { z } from "zod";

/**
 * Payout-prerequisites API client (workstream D3) — KYC, tax profile,
 * payout methods (/api/verification/*) plus the per-combine payout-request
 * adjudication feed (/api/combines/{id}/payout-requests).
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
 * detail string is "<snake_case_code>: <human message>". The payout gates
 * this module routes on are kyc_required / tax_profile_required /
 * payout_method_required — `payoutGateStep()` maps them to the readiness
 * step the user must complete.
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
  // 204s (method delete) have no body to parse.
  if (res.status === 204) return schema.parse(undefined);
  return schema.parse(await res.json());
}

// -- verification status --------------------------------------------------------

export const KYC_STATUSES = [
  "unverified",
  "pending",
  "verified",
  "rejected",
] as const;
export type KycStatus = (typeof KYC_STATUSES)[number];

export const KycOutSchema = z.object({
  /** unverified | pending | verified | rejected */
  status: z.string(),
  reject_reason: z.string().nullable().optional(),
});
export type KycOut = z.infer<typeof KycOutSchema>;

export const TaxOutSchema = z.object({
  submitted: z.boolean(),
  /** W9 | W8BEN when submitted. */
  form_type: z.string().nullable().optional(),
});
export type TaxOut = z.infer<typeof TaxOutSchema>;

/** Masked payout-method shape — rail details never leave the server. */
export const PayoutMethodSchema = z.object({
  id: z.number().int(),
  type: z.string(), // ach | wire | crypto
  label: z.string(),
  is_default: z.boolean(),
  created_at: z.string(),
});
export type PayoutMethod = z.infer<typeof PayoutMethodSchema>;

/** Which prerequisites THIS deployment enforces (mirrors backend settings) —
 *  the readiness flow only blocks on steps whose flag is true. */
export const RequirementsSchema = z.object({
  kyc: z.boolean(),
  tax: z.boolean(),
  method: z.boolean(),
});
export type Requirements = z.infer<typeof RequirementsSchema>;

export const VerificationStatusSchema = z.object({
  kyc: KycOutSchema,
  tax: TaxOutSchema,
  payout_methods: z.array(PayoutMethodSchema),
  requirements: RequirementsSchema,
});
export type VerificationStatus = z.infer<typeof VerificationStatusSchema>;

/** Shared react-query key so KYC/tax/method state stays coherent across the
 *  readiness section and the request-payout gating. */
export const VERIFICATION_STATUS_KEY = ["verification", "status"] as const;

export const fetchVerificationStatus = (): Promise<VerificationStatus> =>
  requestJson("/api/verification/status", VerificationStatusSchema);

// -- KYC -------------------------------------------------------------------------

export const KYC_DOCUMENT_TYPES = [
  "passport",
  "drivers_license",
  "national_id",
] as const;
export type KycDocumentType = (typeof KYC_DOCUMENT_TYPES)[number];

export const KYC_DOCUMENT_LABELS: Record<KycDocumentType, string> = {
  passport: "Passport",
  drivers_license: "Driver's license",
  national_id: "National ID",
};

export interface KycSubmitInput {
  legal_name: string;
  /** "YYYY-MM-DD" — must be 18+. */
  dob: string;
  /** ISO-3166 alpha-2. */
  country: string;
  document_type: KycDocumentType;
}

/** Submit (or resubmit after a rejection) the identity check. The sim
 *  provider decides instantly when auto-verify is on; otherwise the
 *  submission parks at "pending" for human review. */
export const submitKyc = (input: KycSubmitInput): Promise<KycOut> =>
  mutateJson("/api/verification/kyc/submit", KycOutSchema, {
    method: "POST",
    body: JSON.stringify(input),
  });

// -- Tax profile -------------------------------------------------------------------

export const TAX_FORM_TYPES = ["W9", "W8BEN"] as const;
export type TaxFormType = (typeof TAX_FORM_TYPES)[number];

export interface TaxAddressInput {
  line1: string;
  line2?: string;
  city: string;
  region: string;
  postal: string;
  country: string;
}

export interface TaxSubmitInput {
  form_type: TaxFormType;
  legal_name: string;
  /** W9 pins this to US; W8BEN rejects US — the backend enforces it too. */
  country: string;
  address: TaxAddressInput;
  /** Last 4 of SSN/EIN (W-9) or foreign TIN (W-8BEN); exactly 4 digits. */
  tin_last4?: string | null;
}

/** Upsert the tax declaration (one per user — resubmitting replaces it). */
export const submitTaxProfile = (input: TaxSubmitInput): Promise<TaxOut> =>
  mutateJson("/api/verification/tax/submit", TaxOutSchema, {
    method: "POST",
    body: JSON.stringify(input),
  });

// -- Payout methods ---------------------------------------------------------------

export const PAYOUT_METHOD_TYPES = ["ach", "wire", "crypto"] as const;
export type PayoutMethodType = (typeof PAYOUT_METHOD_TYPES)[number];

export const CRYPTO_NETWORKS = ["USDC-ERC20", "USDC-SOL", "BTC"] as const;
export type CryptoNetwork = (typeof CRYPTO_NETWORKS)[number];

export interface PayoutMethodInput {
  type: PayoutMethodType;
  label: string;
  /** Rail-specific: ach {routing_number, account_last4}, wire {bank_name,
   *  swift, account_last4}, crypto {network, address}. The backend
   *  whitelists these keys — anything else is dropped before storage. */
  details: Record<string, string>;
}

export const addPayoutMethod = (
  input: PayoutMethodInput,
): Promise<PayoutMethod> =>
  mutateJson("/api/verification/methods", PayoutMethodSchema, {
    method: "POST",
    body: JSON.stringify(input),
  });

export const removePayoutMethod = (id: number): Promise<void> =>
  mutateJson(`/api/verification/methods/${id}`, z.void(), {
    method: "DELETE",
  });

/** Returns the full masked list so the caller refreshes in one call. */
export const setDefaultPayoutMethod = (
  id: number,
): Promise<PayoutMethod[]> =>
  mutateJson(`/api/verification/methods/${id}/default`, z.array(PayoutMethodSchema), {
    method: "POST",
  });

// -- Payout-request adjudication feed ----------------------------------------------

export const PAYOUT_REQUEST_STATES = [
  "requested",
  "under_review",
  "approved",
  "denied",
  "held",
  "paid",
  // Lifecycle void (account reset, refund/chargeback archival) — terminal,
  // no ledger movement either way.
  "cancelled",
] as const;
export type PayoutRequestState = (typeof PAYOUT_REQUEST_STATES)[number];

export const PayoutRequestSchema = z.object({
  id: z.number().int(),
  amount: z.number(),
  /** requested | under_review | approved | denied | held | paid */
  state: z.string(),
  reason_code: z.string().nullable(),
  reason_label: z.string().nullable(),
  note: z.string().nullable(),
  requested_at: z.string(),
  decided_at: z.string().nullable(),
});
export type PayoutRequest = z.infer<typeof PayoutRequestSchema>;

/** Keyed under ["combines", …] deliberately: useRequestPayout invalidates the
 *  COMBINES_KEY prefix, which sweeps these in with the same brush. */
export const payoutRequestsKey = (combineId: number) =>
  ["combines", combineId, "payout-requests"] as const;

/** The combine's payout-request workflow rows, newest first — where each
 *  request stands and, on a denial, the reason + reviewer note. */
export const fetchPayoutRequests = (
  combineId: number,
): Promise<PayoutRequest[]> =>
  requestJson(
    `/api/combines/${combineId}/payout-requests`,
    z.array(PayoutRequestSchema),
  );

// -- Gate-error routing --------------------------------------------------------------

export type PayoutGateStep = "kyc" | "tax" | "method";

const GATE_CODE_TO_STEP: Record<string, PayoutGateStep> = {
  kyc_required: "kyc",
  tax_profile_required: "tax",
  payout_method_required: "method",
};

/** Map a POST /payout 403 gate error ("kyc_required: …" etc.) to the
 *  readiness step that unblocks it. Null for any other error. */
export function payoutGateStep(err: unknown): PayoutGateStep | null {
  const message = (err as Error)?.message;
  if (typeof message !== "string") return null;
  const m = /^([a-z][a-z0-9_]*):\s/.exec(message);
  return m ? (GATE_CODE_TO_STEP[m[1]] ?? null) : null;
}
