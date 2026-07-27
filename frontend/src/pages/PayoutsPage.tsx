import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { FundedAgreementModal } from "@/components/combines/FundedAgreementModal";
import { PageHeader } from "@/components/layout/PageHeader";
import { Modal } from "@/components/ui/Modal";
import { EmptyState } from "@/components/ui/EmptyState";
import { LoadError } from "@/components/ui/LoadError";
import { MetricPill } from "@/components/ui/MetricPill";
import {
  useActivateAccount,
  useCombines,
  useRequestPayout,
} from "@/hooks/useCombines";
import {
  LEGAL_STATUS_KEY,
  errorCode,
  fetchLegalStatus,
} from "@/lib/legalApi";
import { COUNTRIES } from "@/lib/countries";
import { splitPct, splitTokenFromValue } from "@/lib/pricing";
import {
  CRYPTO_NETWORKS,
  KYC_DOCUMENT_LABELS,
  KYC_DOCUMENT_TYPES,
  VERIFICATION_STATUS_KEY,
  addPayoutMethod,
  fetchPayoutRequests,
  fetchVerificationStatus,
  payoutGateStep,
  payoutRequestsKey,
  removePayoutMethod,
  setDefaultPayoutMethod,
  submitKyc,
  submitTaxProfile,
  type KycDocumentType,
  type PayoutGateStep,
  type PayoutMethod,
  type PayoutMethodType,
  type PayoutRequest,
  type TaxFormType,
  type VerificationStatus,
} from "@/lib/verificationApi";
import { toast } from "@/stores/toast";
import type { CombineOut } from "@/types/combine";

/**
 * /payouts — funded-account payouts (Topstep's Payouts tab). Lists every
 * FUNDED combine with its available payout (the trader's chosen 80/20 or
 * 50/50 split of realized profit, net of prior requests), the split math
 * spelled out, and a request flow: pick an amount (defaults to the max
 * eligible), confirm, and the backend's payout gates (minimum, winning-day
 * count, 24h spacing, MLL buffer) answer with a 409 detail we surface
 * verbatim. Accounts on the activation path must pay the one-time $149 fee
 * first. Simulated: requesting logs an event and moves no money.
 *
 * D3 additions:
 *  - Payout readiness: KYC / tax-form / payout-method onboarding, driven by
 *    GET /api/verification/status. Steps whose `requirements` flag is on
 *    gate the request button; a POST /payout 403 gate code opens the step
 *    that unblocks it. All required steps met → a compact "✓ Payout-ready"
 *    strip (expandable to manage methods).
 *  - Adjudication history: the per-combine payout-request workflow rows
 *    (requested / under_review / approved / denied / held / paid) with a
 *    denial's reason + reviewer note inline. Money semantics unchanged:
 *    debited at REQUEST time; a denial re-credits.
 */
export function PayoutsPage() {
  const { data, isPending, isError, refetch } = useCombines();
  const verification = useVerificationStatus();
  // Which readiness step is expanded — page-level so a payout 403 gate code
  // (kyc_required / tax_profile_required / payout_method_required) can open
  // the exact step the trader must complete.
  const [openStep, setOpenStep] = useState<PayoutGateStep | null>(null);

  const all = data?.combines ?? [];
  const funded = all.filter((c) => c.funded && c.status !== "archived");
  const totalAvailable = funded.reduce((s, c) => s + c.payout_eligible, 0);
  const totalRequested = funded.reduce((s, c) => s + c.payout_requested, 0);

  const unmet = verification.data
    ? unmetRequiredSteps(verification.data)
    : [];
  const gateBlocked = unmet.length > 0;
  const gateHint = gateBlocked
    ? `Complete payout readiness first — ${unmet
        .map((s) => STEP_TITLES[s].toLowerCase())
        .join(", ")}.`
    : undefined;

  return (
    <div className="flex flex-col h-full min-h-0 bg-tier-0">
      <PageHeader
        title="Payouts"
        subtitle="Funded accounts · your share of profit, on request (simulated)"
      />
      <main className="flex-1 min-h-0 overflow-y-auto border-t border-hairline">
        <div className="p-3.5 flex flex-col gap-3.5 min-h-full">
          <div className="flex items-center gap-3 flex-wrap">
            <MetricPill label="FUNDED ACCOUNTS" value={String(funded.length)} />
            <MetricPill label="AVAILABLE" value={formatDollar(totalAvailable)} />
            <MetricPill label="REQUESTED (LIFETIME)" value={formatDollar(totalRequested)} />
          </div>

          <PayoutReadiness
            query={verification}
            openStep={openStep}
            onOpenStep={setOpenStep}
          />

          {isPending ? (
            <div className="px-1 py-6 text-tiny text-fg-tertiary-2">Loading…</div>
          ) : isError ? (
            <LoadError subject="your payouts" onRetry={refetch} />
          ) : funded.length === 0 ? (
            <div className="flex-1 flex items-center justify-center">
              <EmptyState
                title="No funded accounts yet"
                body="Pass an evaluation — hit the profit target with the minimum trading days and consistency — and the account auto-funds. Your payouts appear here once it does."
                action={
                  <Link
                    to="/dashboard"
                    className="h-9 px-4 inline-flex items-center uppercase tracking-label-up border border-amber text-amber bg-tier-1 hover:bg-tier-2 rounded-btn font-medium"
                    style={{ fontSize: 12 }}
                  >
                    Track your progress →
                  </Link>
                }
              />
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              {funded.map((c) => (
                <PayoutRow
                  key={c.id}
                  combine={c}
                  gateBlocked={gateBlocked}
                  gateHint={gateHint}
                  onGateStep={setOpenStep}
                />
              ))}
            </div>
          )}

          <AdjudicationHistory combines={funded} />

          <span className="text-tiny text-fg-tertiary-2 leading-relaxed">
            Payouts are simulated — requesting records the event and moves no
            real money. The amount is debited from your available balance the
            moment you request it; if a request is denied, the amount is
            re-credited. Your split (80/20 or 50/50) and any activation fee
            were set when you bought the combine.
          </span>
        </div>
      </main>
    </div>
  );
}

// ── Payout readiness (KYC / tax / method onboarding) ─────────────────────────

const STEP_TITLES: Record<PayoutGateStep, string> = {
  kyc: "Verify identity",
  tax: "Tax form",
  method: "Payout method",
};

/** Required-and-unmet prerequisites, in step order. Empty = payout-ready.
 *  Only steps whose `requirements` flag is on can block — the backend only
 *  enforces the gates this deployment enabled. */
export function unmetRequiredSteps(v: VerificationStatus): PayoutGateStep[] {
  const out: PayoutGateStep[] = [];
  if (v.requirements.kyc && v.kyc.status !== "verified") out.push("kyc");
  if (v.requirements.tax && !v.tax.submitted) out.push("tax");
  if (v.requirements.method && v.payout_methods.length === 0) out.push("method");
  return out;
}

function useVerificationStatus() {
  return useQuery({
    queryKey: VERIFICATION_STATUS_KEY,
    queryFn: fetchVerificationStatus,
    staleTime: 30_000,
  });
}

function PayoutReadiness({
  query,
  openStep,
  onOpenStep,
}: {
  query: ReturnType<typeof useVerificationStatus>;
  openStep: PayoutGateStep | null;
  onOpenStep: (s: PayoutGateStep | null) => void;
}) {
  // When everything required is on file the section collapses to a strip;
  // "Manage" (or a gate error setting openStep) re-expands it so methods
  // can still be added/removed after the fact.
  const [manageOpen, setManageOpen] = useState(false);

  if (query.isPending) {
    return (
      <div
        className="border border-hairline-strong bg-tier-1 px-3 py-2 text-tiny text-fg-tertiary-2"
        style={{ borderRadius: 4 }}
      >
        Checking payout readiness…
      </div>
    );
  }
  if (query.isError || !query.data) {
    return (
      <div
        className="border border-hairline-strong bg-tier-1 px-3 py-2 flex items-center gap-3"
        style={{ borderRadius: 4 }}
      >
        <span className="text-tiny text-fg-tertiary-2">
          Couldn't check payout readiness.
        </span>
        <button
          type="button"
          onClick={() => query.refetch()}
          className="text-tiny uppercase tracking-label-up text-amber hover:underline"
        >
          Retry
        </button>
      </div>
    );
  }

  const v = query.data;
  const ready = unmetRequiredSteps(v).length === 0;
  const expanded = !ready || manageOpen || openStep != null;

  if (!expanded) {
    return (
      <div
        className="border border-hairline-strong bg-tier-1 flex items-center gap-2 px-3 py-1.5"
        style={{ borderRadius: 4 }}
      >
        <span className="text-bullish" aria-hidden>
          ✓
        </span>
        <span className="text-tiny uppercase tracking-label-up text-bullish">
          Payout-ready
        </span>
        <span className="text-tiny text-fg-tertiary-2 truncate">
          Identity, tax form, and payout method requirements are met.
        </span>
        <button
          type="button"
          onClick={() => setManageOpen(true)}
          className="ml-auto text-tiny uppercase tracking-label-up text-fg-tertiary-2 hover:text-fg-primary shrink-0"
        >
          Manage
        </button>
      </div>
    );
  }

  const toggle = (s: PayoutGateStep) => onOpenStep(openStep === s ? null : s);

  return (
    <div className="border border-hairline-strong bg-tier-1" style={{ borderRadius: 4 }}>
      <div className="flex items-baseline justify-between px-3 py-1.5 border-b border-hairline">
        <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
          Payout readiness
        </span>
        <div className="flex items-center gap-3">
          {ready ? (
            <span className="uppercase tracking-label-up text-bullish" style={{ fontSize: 11 }}>
              ✓ Ready
            </span>
          ) : (
            <span className="uppercase tracking-label-up text-warning" style={{ fontSize: 11 }}>
              Required before your first payout
            </span>
          )}
          {ready && (
            <button
              type="button"
              onClick={() => {
                setManageOpen(false);
                onOpenStep(null);
              }}
              className="text-tiny uppercase tracking-label-up text-fg-tertiary-2 hover:text-fg-primary"
            >
              Collapse
            </button>
          )}
        </div>
      </div>

      <StepCard
        index={1}
        title={STEP_TITLES.kyc}
        chip={kycChip(v)}
        open={openStep === "kyc"}
        onToggle={() => toggle("kyc")}
      >
        <KycStepBody kyc={v.kyc} />
      </StepCard>
      <StepCard
        index={2}
        title={STEP_TITLES.tax}
        chip={taxChip(v)}
        open={openStep === "tax"}
        onToggle={() => toggle("tax")}
      >
        <TaxStepBody tax={v.tax} />
      </StepCard>
      <StepCard
        index={3}
        title={STEP_TITLES.method}
        chip={methodChip(v)}
        open={openStep === "method"}
        onToggle={() => toggle("method")}
      >
        <MethodsStepBody methods={v.payout_methods} />
      </StepCard>
    </div>
  );
}

function kycChip(v: VerificationStatus): ReactNode {
  switch (v.kyc.status) {
    case "verified":
      return <StatusChip tone="ok">Verified</StatusChip>;
    case "pending":
      return <StatusChip tone="warn">Under review</StatusChip>;
    case "rejected":
      return <StatusChip tone="bad">Rejected</StatusChip>;
    default:
      return v.requirements.kyc ? (
        <StatusChip tone="warn">Action needed</StatusChip>
      ) : (
        <StatusChip tone="dim">Optional</StatusChip>
      );
  }
}

function taxChip(v: VerificationStatus): ReactNode {
  if (v.tax.submitted) {
    const label = v.tax.form_type === "W8BEN" ? "W-8BEN on file" : "W-9 on file";
    return <StatusChip tone="ok">{label}</StatusChip>;
  }
  return v.requirements.tax ? (
    <StatusChip tone="warn">Action needed</StatusChip>
  ) : (
    <StatusChip tone="dim">Optional</StatusChip>
  );
}

function methodChip(v: VerificationStatus): ReactNode {
  const n = v.payout_methods.length;
  if (n > 0) {
    return (
      <StatusChip tone="ok">
        {n} on file
      </StatusChip>
    );
  }
  return v.requirements.method ? (
    <StatusChip tone="warn">Action needed</StatusChip>
  ) : (
    <StatusChip tone="dim">Optional</StatusChip>
  );
}

function StatusChip({
  tone,
  children,
}: {
  tone: "ok" | "warn" | "bad" | "dim";
  children: ReactNode;
}) {
  const cls =
    tone === "ok"
      ? "border-bullish text-bullish"
      : tone === "warn"
        ? "border-warning text-warning"
        : tone === "bad"
          ? "border-bearish text-bearish"
          : "border-hairline-strong text-fg-tertiary-2";
  return (
    <span
      className={`border px-1 uppercase tracking-label-up shrink-0 ${cls}`}
      style={{ fontSize: 11, borderRadius: 2 }}
    >
      {children}
    </span>
  );
}

function StepCard({
  index,
  title,
  chip,
  open,
  onToggle,
  children,
}: {
  index: number;
  title: string;
  chip: ReactNode;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  return (
    <div className="border-t border-hairline first:border-t-0">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="w-full flex items-center gap-2.5 px-3 py-2 text-left hover:bg-tier-2 transition-colors duration-75"
      >
        <span
          className="w-5 h-5 flex items-center justify-center border border-hairline-strong text-fg-tertiary-2 tabular-nums shrink-0"
          style={{ fontSize: 11, borderRadius: 2 }}
          aria-hidden
        >
          {index}
        </span>
        <span className="text-sm text-fg-primary">{title}</span>
        {chip}
        <span className="ml-auto text-fg-tertiary-2 shrink-0" style={{ fontSize: 11 }} aria-hidden>
          {open ? "▾" : "▸"}
        </span>
      </button>
      {open && <div className="px-3 pb-3 pt-1">{children}</div>}
    </div>
  );
}

const INPUT_CLS =
  "h-8 px-2 bg-tier-2 border border-tier-3 rounded-btn text-fg-primary focus:border-amber focus:outline-none";

function Field({
  label,
  className,
  children,
}: {
  label: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <label className={`flex flex-col gap-1 min-w-0 ${className ?? ""}`}>
      <span className="uppercase tracking-label-up text-fg-tertiary-2" style={{ fontSize: 11 }}>
        {label}
      </span>
      {children}
    </label>
  );
}

function SubmitButton({
  disabled,
  pending,
  children,
}: {
  disabled: boolean;
  pending: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="submit"
      disabled={disabled || pending}
      className="h-8 px-3 text-tiny uppercase tracking-label-up border border-amber text-amber hover:bg-tier-2 disabled:opacity-40 disabled:cursor-not-allowed self-start"
      style={{ borderRadius: 0 }}
    >
      {pending ? "Submitting…" : children}
    </button>
  );
}

// -- Step 1: KYC ----------------------------------------------------------------

function KycStepBody({ kyc }: { kyc: VerificationStatus["kyc"] }) {
  if (kyc.status === "verified") {
    return (
      <p className="text-tiny text-bullish m-0">
        Identity verified — nothing more to do here.
      </p>
    );
  }
  if (kyc.status === "pending") {
    return (
      <p className="text-tiny text-fg-tertiary m-0 leading-relaxed">
        Your identity submission is <span className="text-warning">under review</span>.
        You'll be able to request payouts once it's verified — check back soon.
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-2.5">
      {kyc.status === "rejected" && (
        <div
          className="border border-bearish px-2.5 py-1.5 text-tiny text-bearish leading-relaxed"
          style={{ borderRadius: 2 }}
          role="alert"
        >
          Verification was rejected
          {kyc.reject_reason ? ` — ${kyc.reject_reason}` : "."} You can resubmit
          below.
        </div>
      )}
      <KycForm resubmit={kyc.status === "rejected"} />
    </div>
  );
}

function KycForm({ resubmit }: { resubmit: boolean }) {
  const qc = useQueryClient();
  const [legalName, setLegalName] = useState("");
  const [dob, setDob] = useState("");
  const [country, setCountry] = useState("US");
  const [docType, setDocType] = useState<KycDocumentType>("passport");

  const submit = useMutation({
    mutationFn: submitKyc,
    onSuccess: (out) => {
      qc.invalidateQueries({ queryKey: VERIFICATION_STATUS_KEY });
      if (out.status === "verified") {
        toast.success("Identity verified.");
      } else if (out.status === "rejected") {
        toast.error(out.reject_reason || "Identity verification was declined.");
      } else {
        toast.info("Identity submitted — under review.");
      }
    },
    onError: (e) => toast.error((e as Error)?.message || "Could not submit"),
  });

  const valid = legalName.trim().length > 0 && dob !== "" && country !== "";

  return (
    <form
      className="flex flex-col gap-2.5"
      onSubmit={(e) => {
        e.preventDefault();
        if (!valid || submit.isPending) return;
        submit.mutate({
          legal_name: legalName.trim(),
          dob,
          country,
          document_type: docType,
        });
      }}
    >
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5" style={{ maxWidth: 560 }}>
        <Field label="Legal name">
          <input
            value={legalName}
            onChange={(e) => setLegalName(e.target.value)}
            maxLength={120}
            autoComplete="name"
            className={INPUT_CLS}
            style={{ fontSize: 13 }}
          />
        </Field>
        <Field label="Date of birth">
          <input
            type="date"
            value={dob}
            onChange={(e) => setDob(e.target.value)}
            className={INPUT_CLS}
            style={{ fontSize: 13 }}
          />
        </Field>
        <Field label="Country">
          <select
            value={country}
            onChange={(e) => setCountry(e.target.value)}
            className={INPUT_CLS}
            style={{ fontSize: 13 }}
          >
            {COUNTRIES.map(([code, name]) => (
              <option key={code} value={code}>
                {name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Document type">
          <select
            value={docType}
            onChange={(e) => setDocType(e.target.value as KycDocumentType)}
            className={INPUT_CLS}
            style={{ fontSize: 13 }}
          >
            {KYC_DOCUMENT_TYPES.map((t) => (
              <option key={t} value={t}>
                {KYC_DOCUMENT_LABELS[t]}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <SubmitButton disabled={!valid} pending={submit.isPending}>
        {resubmit ? "Resubmit identity" : "Submit identity"}
      </SubmitButton>
    </form>
  );
}

// -- Step 2: tax form -------------------------------------------------------------

function TaxStepBody({ tax }: { tax: VerificationStatus["tax"] }) {
  const [editing, setEditing] = useState(false);
  if (tax.submitted && !editing) {
    const label = tax.form_type === "W8BEN" ? "W-8BEN" : "W-9";
    return (
      <div className="flex items-center gap-3">
        <p className="text-tiny text-bullish m-0">{label} on file.</p>
        <button
          type="button"
          onClick={() => setEditing(true)}
          className="text-tiny uppercase tracking-label-up text-fg-tertiary-2 hover:text-fg-primary"
        >
          Resubmit
        </button>
      </div>
    );
  }
  return <TaxForm onSubmitted={() => setEditing(false)} />;
}

function TaxForm({ onSubmitted }: { onSubmitted: () => void }) {
  const qc = useQueryClient();
  const [formType, setFormType] = useState<TaxFormType>("W9");
  const [legalName, setLegalName] = useState("");
  const [country, setCountry] = useState("US");
  const [line1, setLine1] = useState("");
  const [line2, setLine2] = useState("");
  const [city, setCity] = useState("");
  const [region, setRegion] = useState("");
  const [postal, setPostal] = useState("");
  const [tin, setTin] = useState("");

  const submit = useMutation({
    mutationFn: submitTaxProfile,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: VERIFICATION_STATUS_KEY });
      toast.success("Tax form submitted.");
      onSubmitted();
    },
    onError: (e) => toast.error((e as Error)?.message || "Could not submit"),
  });

  // A W-9 is the US-person form, a W-8BEN the non-US one — the toggle pins
  // the declared country to its side of that line (the backend enforces the
  // same rule with a 422).
  function pickForm(t: TaxFormType) {
    setFormType(t);
    if (t === "W9") setCountry("US");
    else if (country === "US") setCountry("");
  }

  const tinOk = tin === "" || /^\d{4}$/.test(tin);
  const valid =
    legalName.trim() !== "" &&
    country !== "" &&
    line1.trim() !== "" &&
    city.trim() !== "" &&
    region.trim() !== "" &&
    postal.trim() !== "" &&
    tinOk;

  return (
    <form
      className="flex flex-col gap-2.5"
      onSubmit={(e) => {
        e.preventDefault();
        if (!valid || submit.isPending) return;
        submit.mutate({
          form_type: formType,
          legal_name: legalName.trim(),
          country,
          address: {
            line1: line1.trim(),
            ...(line2.trim() ? { line2: line2.trim() } : {}),
            city: city.trim(),
            region: region.trim(),
            postal: postal.trim(),
            country,
          },
          tin_last4: tin === "" ? null : tin,
        });
      }}
    >
      <div className="flex items-center gap-2">
        {(["W9", "W8BEN"] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => pickForm(t)}
            aria-pressed={formType === t}
            className={[
              "uppercase tracking-label-up rounded-btn px-2 py-1.5 text-tiny",
              formType === t
                ? "bg-tier-3 border border-amber text-amber"
                : "bg-tier-2 border border-tier-3 text-fg-secondary hover:bg-tier-3",
            ].join(" ")}
          >
            {t === "W9" ? "W-9" : "W-8BEN"}
          </button>
        ))}
        <span className="text-tiny text-fg-tertiary-2">
          {formType === "W9"
            ? "For US persons — country is pinned to United States."
            : "For non-US persons — declare your country of residence."}
        </span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5" style={{ maxWidth: 560 }}>
        <Field label="Legal name">
          <input
            value={legalName}
            onChange={(e) => setLegalName(e.target.value)}
            maxLength={120}
            autoComplete="name"
            className={INPUT_CLS}
            style={{ fontSize: 13 }}
          />
        </Field>
        <Field label="Country">
          <select
            value={country}
            onChange={(e) => setCountry(e.target.value)}
            disabled={formType === "W9"}
            className={`${INPUT_CLS} disabled:opacity-60`}
            style={{ fontSize: 13 }}
          >
            {formType === "W8BEN" && <option value="">Select…</option>}
            {COUNTRIES.filter(
              ([code]) => formType === "W9" || code !== "US",
            ).map(([code, name]) => (
              <option key={code} value={code}>
                {name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Address line 1" className="sm:col-span-2">
          <input
            value={line1}
            onChange={(e) => setLine1(e.target.value)}
            maxLength={120}
            autoComplete="address-line1"
            className={INPUT_CLS}
            style={{ fontSize: 13 }}
          />
        </Field>
        <Field label="Address line 2 (optional)" className="sm:col-span-2">
          <input
            value={line2}
            onChange={(e) => setLine2(e.target.value)}
            maxLength={120}
            autoComplete="address-line2"
            className={INPUT_CLS}
            style={{ fontSize: 13 }}
          />
        </Field>
        <Field label="City">
          <input
            value={city}
            onChange={(e) => setCity(e.target.value)}
            maxLength={80}
            autoComplete="address-level2"
            className={INPUT_CLS}
            style={{ fontSize: 13 }}
          />
        </Field>
        <Field label="State / region">
          <input
            value={region}
            onChange={(e) => setRegion(e.target.value)}
            maxLength={80}
            autoComplete="address-level1"
            className={INPUT_CLS}
            style={{ fontSize: 13 }}
          />
        </Field>
        <Field label="Postal code">
          <input
            value={postal}
            onChange={(e) => setPostal(e.target.value)}
            maxLength={20}
            autoComplete="postal-code"
            className={INPUT_CLS}
            style={{ fontSize: 13 }}
          />
        </Field>
        <Field
          label={
            formType === "W9" ? "SSN/EIN last 4 (optional)" : "TIN last 4 (optional)"
          }
        >
          <input
            value={tin}
            onChange={(e) => setTin(e.target.value.replace(/\D/g, "").slice(0, 4))}
            inputMode="numeric"
            maxLength={4}
            placeholder="••••"
            className={`${INPUT_CLS} tabular-nums`}
            style={{ fontSize: 13 }}
          />
        </Field>
      </div>
      {!tinOk && (
        <span className="text-tiny text-warning">
          The TIN field takes exactly the last 4 digits.
        </span>
      )}
      <SubmitButton disabled={!valid} pending={submit.isPending}>
        Submit {formType === "W9" ? "W-9" : "W-8BEN"}
      </SubmitButton>
    </form>
  );
}

// -- Step 3: payout methods ----------------------------------------------------------

function MethodsStepBody({ methods }: { methods: PayoutMethod[] }) {
  const qc = useQueryClient();
  const invalidate = () =>
    qc.invalidateQueries({ queryKey: VERIFICATION_STATUS_KEY });
  // With nothing on file the add form is the whole step; once methods exist
  // it collapses behind "+ Add method".
  const [adding, setAdding] = useState(false);
  const showForm = adding || methods.length === 0;

  const remove = useMutation({
    mutationFn: removePayoutMethod,
    onSuccess: () => {
      invalidate();
      toast.info("Payout method removed.");
    },
    onError: (e) => toast.error((e as Error)?.message || "Could not remove"),
  });
  const makeDefault = useMutation({
    mutationFn: setDefaultPayoutMethod,
    onSuccess: () => invalidate(),
    onError: (e) => toast.error((e as Error)?.message || "Could not set default"),
  });

  return (
    <div className="flex flex-col gap-2.5">
      {methods.length > 0 && (
        <ul className="flex flex-col gap-1">
          {methods.map((m) => (
            <li
              key={m.id}
              className="flex items-center gap-2 border border-hairline px-2.5 py-1.5 bg-tier-2"
              style={{ borderRadius: 2 }}
            >
              <span
                className="border border-hairline-strong text-fg-tertiary-2 px-1 uppercase tracking-label-up shrink-0"
                style={{ fontSize: 11, borderRadius: 2 }}
              >
                {m.type}
              </span>
              <span className="text-sm text-fg-primary truncate">{m.label}</span>
              {m.is_default ? (
                <span
                  className="border border-amber text-amber px-1 uppercase tracking-label-up shrink-0"
                  style={{ fontSize: 11, borderRadius: 2 }}
                >
                  Default
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() => makeDefault.mutate(m.id)}
                  disabled={makeDefault.isPending}
                  className="text-tiny uppercase tracking-label-up text-fg-tertiary-2 hover:text-fg-primary disabled:opacity-40 shrink-0"
                >
                  Set default
                </button>
              )}
              <button
                type="button"
                onClick={() => remove.mutate(m.id)}
                disabled={remove.isPending}
                aria-label={`Remove payout method ${m.label}`}
                className="ml-auto text-medium leading-none text-fg-tertiary hover:text-bearish px-1 shrink-0"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
      {showForm ? (
        <AddMethodForm onDone={() => setAdding(false)} />
      ) : (
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="self-start text-tiny uppercase tracking-label-up text-amber hover:underline"
        >
          + Add method
        </button>
      )}
    </div>
  );
}

function AddMethodForm({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient();
  const [type, setType] = useState<PayoutMethodType>("ach");
  const [label, setLabel] = useState("");
  // ACH
  const [routing, setRouting] = useState("");
  const [achLast4, setAchLast4] = useState("");
  // Wire
  const [bankName, setBankName] = useState("");
  const [swift, setSwift] = useState("");
  const [wireLast4, setWireLast4] = useState("");
  // Crypto
  const [network, setNetwork] = useState<string>(CRYPTO_NETWORKS[0]);
  const [address, setAddress] = useState("");

  const submit = useMutation({
    mutationFn: addPayoutMethod,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: VERIFICATION_STATUS_KEY });
      toast.success("Payout method added.");
      onDone();
    },
    onError: (e) => toast.error((e as Error)?.message || "Could not add method"),
  });

  const details: Record<string, string> =
    type === "ach"
      ? { routing_number: routing, account_last4: achLast4 }
      : type === "wire"
        ? { bank_name: bankName.trim(), swift: swift.trim(), account_last4: wireLast4 }
        : { network, address: address.trim() };

  const railValid =
    type === "ach"
      ? /^\d{9}$/.test(routing) && /^\d{4}$/.test(achLast4)
      : type === "wire"
        ? bankName.trim() !== "" && swift.trim() !== "" && /^\d{4}$/.test(wireLast4)
        : address.trim() !== "";
  const valid = label.trim() !== "" && railValid;

  const digits = (v: string, n: number) => v.replace(/\D/g, "").slice(0, n);

  return (
    <form
      className="flex flex-col gap-2.5"
      onSubmit={(e) => {
        e.preventDefault();
        if (!valid || submit.isPending) return;
        submit.mutate({ type, label: label.trim(), details });
      }}
    >
      <div className="flex items-center gap-2">
        {(["ach", "wire", "crypto"] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setType(t)}
            aria-pressed={type === t}
            className={[
              "uppercase tracking-label-up rounded-btn px-2 py-1.5 text-tiny",
              type === t
                ? "bg-tier-3 border border-amber text-amber"
                : "bg-tier-2 border border-tier-3 text-fg-secondary hover:bg-tier-3",
            ].join(" ")}
          >
            {t === "ach" ? "ACH" : t === "wire" ? "Wire" : "Crypto"}
          </button>
        ))}
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5" style={{ maxWidth: 560 }}>
        <Field label="Label" className="sm:col-span-2">
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            maxLength={64}
            placeholder={
              type === "ach"
                ? "e.g. Chase checking"
                : type === "wire"
                  ? "e.g. HSBC wire"
                  : "e.g. Cold wallet"
            }
            className={INPUT_CLS}
            style={{ fontSize: 13 }}
          />
        </Field>
        {type === "ach" && (
          <>
            <Field label="Routing number (9 digits)">
              <input
                value={routing}
                onChange={(e) => setRouting(digits(e.target.value, 9))}
                inputMode="numeric"
                maxLength={9}
                className={`${INPUT_CLS} tabular-nums`}
                style={{ fontSize: 13 }}
              />
            </Field>
            <Field label="Account — last 4">
              <input
                value={achLast4}
                onChange={(e) => setAchLast4(digits(e.target.value, 4))}
                inputMode="numeric"
                maxLength={4}
                placeholder="••••"
                className={`${INPUT_CLS} tabular-nums`}
                style={{ fontSize: 13 }}
              />
            </Field>
          </>
        )}
        {type === "wire" && (
          <>
            <Field label="Bank name">
              <input
                value={bankName}
                onChange={(e) => setBankName(e.target.value)}
                className={INPUT_CLS}
                style={{ fontSize: 13 }}
              />
            </Field>
            <Field label="SWIFT / BIC">
              <input
                value={swift}
                onChange={(e) => setSwift(e.target.value.toUpperCase())}
                className={INPUT_CLS}
                style={{ fontSize: 13 }}
              />
            </Field>
            <Field label="Account — last 4">
              <input
                value={wireLast4}
                onChange={(e) => setWireLast4(digits(e.target.value, 4))}
                inputMode="numeric"
                maxLength={4}
                placeholder="••••"
                className={`${INPUT_CLS} tabular-nums`}
                style={{ fontSize: 13 }}
              />
            </Field>
          </>
        )}
        {type === "crypto" && (
          <>
            <Field label="Network">
              <select
                value={network}
                onChange={(e) => setNetwork(e.target.value)}
                className={INPUT_CLS}
                style={{ fontSize: 13 }}
              >
                {CRYPTO_NETWORKS.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Wallet address">
              <input
                value={address}
                onChange={(e) => setAddress(e.target.value)}
                spellCheck={false}
                className={`${INPUT_CLS} font-mono`}
                style={{ fontSize: 13 }}
              />
            </Field>
          </>
        )}
      </div>
      <span className="text-tiny text-fg-tertiary-2">
        Only the fields above are stored — full account numbers never leave
        your bank.
      </span>
      <div className="flex items-center gap-2">
        <SubmitButton disabled={!valid} pending={submit.isPending}>
          Add {type === "ach" ? "ACH" : type} method
        </SubmitButton>
        <button
          type="button"
          onClick={onDone}
          className="h-8 px-3 text-tiny uppercase tracking-label-up text-fg-tertiary-2 hover:text-fg-primary"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

// ── Funded-account rows ──────────────────────────────────────────────────────

function PayoutRow({
  combine,
  gateBlocked,
  gateHint,
  onGateStep,
}: {
  combine: CombineOut;
  gateBlocked: boolean;
  gateHint?: string;
  onGateStep: (s: PayoutGateStep) => void;
}) {
  const payout = useRequestPayout();
  const activate = useActivateAccount();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const available = combine.payout_eligible;
  const needsActivation = combine.activation_required;

  // Funded-agreement e-sign gate — same recovery pattern as CombineCards:
  // activation 403s "agreement_required: …" until the agreement is signed,
  // so an unsigned trader gets the modal instead of a dead-end toast.
  const [agreementOpen, setAgreementOpen] = useState(false);
  const { data: legalStatus } = useQuery({
    queryKey: LEGAL_STATUS_KEY,
    queryFn: fetchLegalStatus,
    staleTime: 60_000,
    enabled: needsActivation,
  });
  const agreementSigned = legalStatus?.funded_agreement?.current === true;
  const runActivation = () => {
    activate.mutate(combine.id, {
      onSuccess: () => setAgreementOpen(false),
      onError: (e) => {
        if (errorCode(e) === "agreement_required") setAgreementOpen(true);
      },
    });
  };
  const startActivation = () => {
    if (agreementSigned) runActivation();
    else setAgreementOpen(true);
  };
  const profit = Math.max(0, combine.realized_pnl);
  const pct = splitPct(splitTokenFromValue(combine.profit_split));
  const splitText = `${pct}%`;
  return (
    <div
      className="border border-hairline-strong bg-tier-1 flex items-center gap-4 px-3 py-2.5"
      style={{ borderRadius: 4 }}
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-fg-primary font-medium truncate" style={{ fontSize: 13 }}>
            {combine.name}
          </span>
          <span
            className="border border-bullish text-bullish px-1 uppercase tracking-label-up shrink-0"
            style={{ fontSize: 11, borderRadius: 2 }}
          >
            funded
          </span>
          <span
            className="border border-hairline-strong text-fg-tertiary-2 px-1 uppercase tracking-label-up shrink-0"
            style={{ fontSize: 11, borderRadius: 2 }}
          >
            keeps {splitText}
          </span>
        </div>
        <div className="text-fg-tertiary-2 tabular-nums mt-0.5" style={{ fontSize: 12 }}>
          {combine.tier} · {combine.account_code}
        </div>
        {/* The split math, spelled out — where "available" comes from. */}
        {!needsActivation && (
          <div className="text-fg-tertiary tabular-nums mt-0.5" style={{ fontSize: 12 }}>
            {formatDollar(profit)} profit × {splitText} −{" "}
            {formatDollar(combine.payout_requested)} paid ={" "}
            {formatDollar(available)} available
          </div>
        )}
      </div>
      <Figure label="Realized profit" value={formatDollar(profit)} />
      <Figure label="Requested" value={formatDollar(combine.payout_requested)} />
      <Figure
        label="Available"
        value={needsActivation ? "locked" : formatDollar(available)}
        tone={!needsActivation && available > 0 ? "bullish" : undefined}
      />
      {needsActivation ? (
        <button
          type="button"
          disabled={activate.isPending}
          onClick={startActivation}
          title={
            combine.activation_fee > 0
              ? `Activate this funded account — a one-time $${combine.activation_fee} fee unlocks payouts (simulated).`
              : "Activate this funded account — free on the no-activation plan — to unlock payouts."
          }
          className="h-8 px-3 text-tiny uppercase tracking-label-up border border-amber text-amber hover:bg-tier-2 disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
          style={{ borderRadius: 0 }}
        >
          {activate.isPending
            ? "…"
            : combine.activation_fee > 0
              ? `Activate — $${combine.activation_fee}`
              : "Activate — free"}
        </button>
      ) : (
        // A disabled button is unfocusable, so a `title` tooltip alone hides the
        // blocking reason from keyboard + screen-reader users. Surface it as
        // visible text (everyone sees it) and wire it as the button's
        // aria-description so it's announced with the button.
        (() => {
          const reason = gateBlocked
            ? gateHint
            : available <= 0
              ? "No payout available yet."
              : undefined;
          return (
            <span className="shrink-0 flex flex-col items-end gap-0.5" title={reason}>
              <button
                type="button"
                disabled={available <= 0 || gateBlocked}
                onClick={() => {
                  payout.reset();
                  setConfirmOpen(true);
                }}
                aria-describedby={reason ? `payout-reason-${combine.id}` : undefined}
                className="h-8 px-3 text-tiny uppercase tracking-label-up border border-bullish text-bullish hover:bg-tier-2 disabled:opacity-40 disabled:cursor-not-allowed"
                style={{ borderRadius: 0 }}
              >
                Request payout
              </button>
              {reason && (
                <span
                  id={`payout-reason-${combine.id}`}
                  className="text-fg-tertiary-2 text-right"
                  style={{ fontSize: 11, maxWidth: 220 }}
                >
                  {reason}
                </span>
              )}
            </span>
          );
        })()
      )}
      {confirmOpen && (
        <PayoutConfirmDialog
          combine={combine}
          payout={payout}
          onClose={() => setConfirmOpen(false)}
          onGateStep={onGateStep}
        />
      )}
      {needsActivation && (
        <FundedAgreementModal
          combine={combine}
          open={agreementOpen}
          onClose={() => setAgreementOpen(false)}
          onSigned={runActivation}
          activating={activate.isPending}
        />
      )}
    </div>
  );
}

/**
 * Confirm step for a payout request: pick the amount (defaults to the max
 * eligible) and confirm. A backend 409 — the minimum, winning-day, 24h, or
 * MLL-buffer gate — renders its detail verbatim so the trader knows the
 * exact rule that blocked the request. A 403 prerequisite gate
 * (kyc_required / tax_profile_required / payout_method_required) instead
 * closes the dialog and opens the matching readiness step.
 */
function PayoutConfirmDialog({
  combine,
  payout,
  onClose,
  onGateStep,
}: {
  combine: CombineOut;
  payout: ReturnType<typeof useRequestPayout>;
  onClose: () => void;
  onGateStep: (s: PayoutGateStep) => void;
}) {
  const available = combine.payout_eligible;
  const [amountText, setAmountText] = useState(available.toFixed(2));
  const amount = Number(amountText);
  const valid = Number.isFinite(amount) && amount > 0 && amount <= available;
  const profit = Math.max(0, combine.realized_pnl);
  const splitText = `${splitPct(splitTokenFromValue(combine.profit_split))}%`;
  const titleId = `payout-confirm-${combine.id}`;

  return (
    <Modal
      open
      onClose={onClose}
      labelledBy={titleId}
      panelClassName="w-full max-w-sm bg-tier-1 border border-hairline-strong rounded-btn shadow-2xl"
    >
      <form
        className="flex flex-col gap-3 px-4 py-3.5"
        onSubmit={(e) => {
          e.preventDefault();
          if (!valid || payout.isPending) return;
          payout.mutate(
            { id: combine.id, amount },
            {
              onSuccess: onClose,
              onError: (err) => {
                const step = payoutGateStep(err);
                if (step) {
                  onClose();
                  onGateStep(step);
                }
              },
            },
          );
        }}
      >
        <h2 id={titleId} className="text-medium font-medium text-fg-primary m-0">
          Request payout — {combine.name}
        </h2>
        <div className="text-tiny text-fg-tertiary tabular-nums">
          {formatDollar(profit)} profit × {splitText} −{" "}
          {formatDollar(combine.payout_requested)} paid ={" "}
          <span className="text-fg-secondary">{formatDollar(available)} available</span>
        </div>
        <label className="flex flex-col gap-1">
          <span className="uppercase tracking-label-up text-fg-tertiary-2" style={{ fontSize: 11 }}>
            Amount
          </span>
          <input
            type="number"
            inputMode="decimal"
            min={0}
            max={available}
            step={0.01}
            value={amountText}
            onChange={(e) => setAmountText(e.target.value)}
            className="h-8 px-2 bg-tier-2 border border-tier-3 rounded-btn text-fg-primary text-right tabular-nums focus:border-amber focus:outline-none"
            style={{ fontSize: 13 }}
            aria-label="Payout amount"
          />
        </label>
        {!valid && amountText.trim() !== "" && (
          <span className="text-tiny text-warning">
            Enter an amount between $0.01 and {formatDollar(available)}.
          </span>
        )}
        {payout.isError && (
          <div className="text-tiny text-bearish leading-relaxed" role="alert">
            {(payout.error as Error).message}
          </div>
        )}
        <span className="text-tiny text-fg-tertiary-2 leading-relaxed">
          The amount is debited from your available balance now and held while
          the request is reviewed; a denial re-credits it.
        </span>
        <div className="flex items-center justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={onClose}
            className="h-8 px-3 text-tiny uppercase tracking-label-up text-fg-tertiary-2 hover:text-fg-primary"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={!valid || payout.isPending}
            className="h-8 px-3 text-tiny uppercase tracking-label-up border border-bullish text-bullish hover:bg-tier-2 disabled:opacity-40 disabled:cursor-not-allowed"
            style={{ borderRadius: 0 }}
          >
            {payout.isPending ? "Requesting…" : `Confirm — ${formatDollar(valid ? amount : 0)}`}
          </button>
        </div>
      </form>
    </Modal>
  );
}

// ── Adjudication history (payout-request workflow rows) ──────────────────────

const STATE_CHIPS: Record<
  string,
  { label: string; cls: string; hint: string }
> = {
  requested: {
    label: "REQUESTED",
    cls: "border-hairline-strong text-fg-secondary",
    hint: "Awaiting review — the amount is already held against your balance.",
  },
  under_review: {
    label: "IN REVIEW",
    cls: "border-warning bg-warning/10 text-warning",
    hint: "A reviewer picked this up — the amount stays held meanwhile.",
  },
  held: {
    label: "HELD",
    cls: "border-warning text-warning",
    hint: "On hold pending further review — the amount stays held meanwhile.",
  },
  approved: {
    label: "APPROVED",
    cls: "border-bullish text-bullish",
    hint: "Approved — disbursement queued (simulated).",
  },
  paid: {
    label: "PAID",
    cls: "border-bullish bg-bullish text-tier-0",
    hint: "Paid out (simulated).",
  },
  denied: {
    label: "DENIED",
    cls: "border-bearish text-bearish",
    hint: "Denied — the amount was re-credited to your available balance.",
  },
  cancelled: {
    label: "CANCELLED",
    cls: "border-hairline-strong text-fg-tertiary-2",
    hint: "Voided by an account lifecycle change (reset or refund) — no money moved.",
  },
};

function StateChip({ state }: { state: string }) {
  const spec = STATE_CHIPS[state] ?? {
    label: state.toUpperCase(),
    cls: "border-hairline-strong text-fg-secondary",
    hint: "",
  };
  return (
    <span
      className={`inline-flex items-center px-1 border uppercase tracking-label-up shrink-0 ${spec.cls}`}
      style={{ fontSize: 11, borderRadius: 2, height: 15 }}
      title={spec.hint || undefined}
    >
      {spec.label}
    </span>
  );
}

/**
 * Every payout request across the funded combines, newest first, with its
 * review state. This is the workflow surface (payout_requests rows) — the
 * money itself moved at REQUEST time (the debit is booked when you ask), so
 * the chips describe review status, not fund movement. Denials carry the
 * reviewer's reason + note behind "Why?".
 */
function AdjudicationHistory({ combines }: { combines: CombineOut[] }) {
  const results = useQueries({
    queries: combines.map((c) => ({
      queryKey: payoutRequestsKey(c.id),
      queryFn: () => fetchPayoutRequests(c.id),
      staleTime: 15_000,
      refetchInterval: 30_000,
    })),
  });

  // Computed inline (no memo): a handful of rows, and useQueries returns a
  // fresh array each render anyway.
  const rows: Array<{ combineName: string; req: PayoutRequest }> = [];
  results.forEach((q, i) => {
    for (const req of q.data ?? []) {
      rows.push({ combineName: combines[i]?.name ?? "—", req });
    }
  });
  rows.sort((a, b) => {
    const dt = Date.parse(b.req.requested_at) - Date.parse(a.req.requested_at);
    return Number.isFinite(dt) && dt !== 0 ? dt : b.req.id - a.req.id;
  });

  const loading = combines.length > 0 && results.some((q) => q.isPending);

  return (
    <div className="border border-hairline-strong bg-tier-1" style={{ borderRadius: 4 }}>
      <div className="flex items-baseline justify-between px-3 py-1.5 border-b border-hairline">
        <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
          Payout requests
        </span>
        <span className="uppercase tracking-label-up text-fg-tertiary-2 tabular-nums" style={{ fontSize: 11 }}>
          {rows.length} request{rows.length === 1 ? "" : "s"}
        </span>
      </div>
      {loading ? (
        <div className="px-3 py-3 text-tiny text-fg-tertiary-2">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="px-3 py-3 text-tiny text-fg-tertiary-2">
          No payout requests yet — each request appears here with its review
          status. Money is debited when you request and re-credited if denied.
        </div>
      ) : (
        <ul className="divide-y divide-hairline">
          {rows.map((r) => (
            <RequestRow key={r.req.id} combineName={r.combineName} req={r.req} />
          ))}
        </ul>
      )}
    </div>
  );
}

function RequestRow({
  combineName,
  req,
}: {
  combineName: string;
  req: PayoutRequest;
}) {
  const [showWhy, setShowWhy] = useState(false);
  const denied = req.state === "denied" || req.state === "cancelled";
  const hasWhy = denied && (req.reason_label != null || req.note != null);
  return (
    <li className="px-3 py-1.5">
      <div className="flex items-baseline gap-3 tabular-nums">
        <span className="text-tiny text-fg-tertiary-2 shrink-0" style={{ minWidth: 84 }}>
          {formatDate(req.requested_at)}
        </span>
        <span className="text-tiny text-fg-secondary truncate flex-1">
          {combineName}
        </span>
        {hasWhy && (
          <button
            type="button"
            onClick={() => setShowWhy((s) => !s)}
            aria-expanded={showWhy}
            className="text-tiny text-bearish hover:underline shrink-0"
          >
            Why?
          </button>
        )}
        <StateChip state={req.state} />
        <span
          className={`text-tiny shrink-0 ${denied ? "text-fg-tertiary-2 line-through" : "text-bullish"}`}
        >
          {formatDollar(req.amount)}
        </span>
      </div>
      {showWhy && hasWhy && (
        <div
          className="mt-1 ml-[84px] text-tiny text-bearish leading-relaxed"
          role="note"
        >
          {req.reason_label ?? "Denied"}
          {req.note ? ` — ${req.note}` : ""}
          <span className="text-fg-tertiary-2">
            {" "}
            The {formatDollar(req.amount)} was re-credited to your available
            balance.
          </span>
        </div>
      )}
    </li>
  );
}

// ── Shared bits ──────────────────────────────────────────────────────────────

function Figure({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "bullish";
}) {
  return (
    <div className="flex flex-col items-end shrink-0" style={{ minWidth: 92 }}>
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 11 }}
      >
        {label}
      </span>
      <span
        className={`text-tiny tabular-nums ${tone === "bullish" ? "text-bullish" : "text-fg-secondary"}`}
      >
        {value}
      </span>
    </div>
  );
}

function formatDollar(v: number): string {
  if (!Number.isFinite(v)) return "—";
  return `$${v.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
  return d.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}
