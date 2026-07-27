import { useState, type ReactNode } from "react";

import { Modal } from "@/components/ui/Modal";

/**
 * Shared operator-console primitives (workstream D1) — the dense
 * "instrument cluster" vocabulary every admin section speaks: hairline
 * panels, uppercase micro-labels, tone chips, stat tiles, table cell
 * classes, and the reason-collecting action modal.
 */

// -- tone system ---------------------------------------------------------------

export type Tone =
  | "neutral"
  | "amber"
  | "cyan"
  | "bullish"
  | "bearish"
  | "warning"
  | "breach"
  | "muted";

const CHIP_TONES: Record<Tone, string> = {
  neutral: "border-hairline-strong text-fg-secondary",
  amber: "border-amber text-amber",
  cyan: "border-cyan text-cyan",
  bullish: "border-bullish text-bullish",
  bearish: "border-bearish text-bearish",
  warning: "border-warning text-warning",
  breach: "border-breach text-breach",
  muted: "border-hairline-strong text-fg-tertiary-2",
};

/** Uppercase micro-chip — states, roles, flags. */
export function Chip({
  tone = "neutral",
  children,
  title,
}: {
  tone?: Tone;
  children: ReactNode;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={`inline-block border px-1 uppercase tracking-label-up whitespace-nowrap ${CHIP_TONES[tone]}`}
      style={{ fontSize: 11, borderRadius: 2 }}
    >
      {children}
    </span>
  );
}

/** Payout-request state → chip tone. requested/under_review are "work to
 *  do" (amber/cyan), held is caution, approved/paid resolve green/quiet,
 *  denied reads bearish. */
export function payoutStateTone(state: string): Tone {
  switch (state) {
    case "requested":
      return "amber";
    case "under_review":
      return "cyan";
    case "held":
      return "warning";
    case "approved":
      return "bullish";
    case "paid":
      return "muted";
    case "denied":
      return "bearish";
    case "cancelled":
      // Lifecycle void (account reset / expired), not a reviewer decision.
      return "neutral";
    default:
      return "neutral";
  }
}

export function kycStatusTone(status: string): Tone {
  switch (status) {
    case "verified":
      return "bullish";
    case "pending":
      return "amber";
    case "rejected":
      return "bearish";
    default:
      return "muted";
  }
}

export function ticketStatusTone(status: string): Tone {
  return status === "open" ? "amber" : status === "replied" ? "bullish" : "muted";
}

// -- buttons ---------------------------------------------------------------------

const BTN_BASE =
  "h-8 px-3 uppercase tracking-label-up rounded-btn font-medium border " +
  "disabled:opacity-50 disabled:cursor-not-allowed transition-colors duration-100";

const BTN_KINDS = {
  primary: "border-amber text-amber bg-tier-2 hover:bg-tier-3",
  danger: "border-bearish text-bearish bg-tier-2 hover:bg-tier-3",
  ghost: "border-tier-3 text-fg-secondary bg-tier-2 hover:bg-tier-3 hover:text-fg-primary",
  success: "border-bullish text-bullish bg-tier-2 hover:bg-tier-3",
} as const;
export type BtnKind = keyof typeof BTN_KINDS;

export function Btn({
  kind = "ghost",
  children,
  className = "",
  type = "button",
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  kind?: BtnKind;
}) {
  return (
    <button
      type={type}
      className={`${BTN_BASE} ${BTN_KINDS[kind]} ${className}`}
      style={{ fontSize: 11 }}
      {...rest}
    >
      {children}
    </button>
  );
}

// -- panels / tiles ----------------------------------------------------------------

/** Hairline panel with an uppercase header label — the console's basic
 *  container (same chrome as SupportPage's form card). */
export function Panel({
  label,
  actions,
  children,
  className = "",
}: {
  label: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`border border-hairline-strong bg-tier-1 flex flex-col ${className}`}
      style={{ borderRadius: 4 }}
    >
      <div className="px-3 py-2 border-b border-hairline flex items-center gap-2">
        <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
          {label}
        </span>
        {actions && <div className="ml-auto flex items-center gap-2">{actions}</div>}
      </div>
      {children}
    </section>
  );
}

/** Dense stat tile — uppercase label over a big tabular number. */
export function StatTile({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  tone?: "amber" | "bullish" | "bearish" | "warning";
}) {
  const valueCls =
    tone === "amber"
      ? "text-amber"
      : tone === "bullish"
        ? "text-bullish"
        : tone === "bearish"
          ? "text-bearish"
          : tone === "warning"
            ? "text-warning"
            : "text-fg-primary";
  return (
    <div
      className="border border-hairline-strong bg-tier-1 px-3 py-2.5 flex flex-col gap-1 min-w-0"
      style={{ borderRadius: 4 }}
    >
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 11 }}
      >
        {label}
      </span>
      <span className={`text-large font-display font-semibold tabular-nums ${valueCls}`}>
        {value}
      </span>
      {hint && (
        <span className="text-tiny text-fg-tertiary normal-case">{hint}</span>
      )}
    </div>
  );
}

// -- table cell classes ----------------------------------------------------------------

export const TH_CLS =
  "px-2 py-1.5 text-left uppercase tracking-label-up text-fg-tertiary-2 font-normal whitespace-nowrap border-b border-hairline";
export const TD_CLS =
  "px-2 py-1.5 text-fg-secondary whitespace-nowrap border-b border-hairline align-top";
export const TABLE_CLS = "w-full border-collapse";
export const TABLE_FONT = { fontSize: 12 } as const;
export const NUM_CLS = "tabular-nums";

// -- filter chips -----------------------------------------------------------------------

/** Row of exclusive filter chips (state / status filters). */
export function FilterChips<K extends string>({
  options,
  value,
  onChange,
}: {
  options: readonly { key: K; label: string }[];
  value: K;
  onChange: (key: K) => void;
}) {
  return (
    <div className="flex items-center gap-1 flex-wrap">
      {options.map((o) => (
        <button
          key={o.key}
          type="button"
          onClick={() => onChange(o.key)}
          className={[
            "px-2 h-6 uppercase tracking-label-up border transition-colors duration-100",
            o.key === value
              ? "border-amber text-amber bg-tier-2"
              : "border-hairline-strong text-fg-tertiary-2 hover:text-fg-primary hover:bg-tier-2",
          ].join(" ")}
          style={{ fontSize: 11, borderRadius: 2 }}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

// -- pagination --------------------------------------------------------------------------

export function Pager({
  page,
  total,
  pageSize,
  onPage,
}: {
  page: number;
  total: number;
  pageSize: number;
  onPage: (page: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="flex items-center gap-2 px-2 py-1.5">
      <span className="text-tiny text-fg-tertiary-2 tabular-nums">
        {total} total · page {page}/{pages}
      </span>
      <div className="ml-auto flex gap-1">
        <Btn kind="ghost" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          Prev
        </Btn>
        <Btn kind="ghost" disabled={page >= pages} onClick={() => onPage(page + 1)}>
          Next
        </Btn>
      </div>
    </div>
  );
}

// -- action modal -----------------------------------------------------------------------

let _modalSeq = 0;

/**
 * Confirm-with-fields modal for admin mutations. The parent owns any field
 * state and renders inputs as `children`; this provides the chrome, the
 * title, and Cancel / Confirm buttons. `disabled` gates Confirm (e.g. a
 * required reason still empty).
 */
export function ActionModal({
  open,
  onClose,
  title,
  description,
  confirmLabel,
  confirmKind = "primary",
  disabled = false,
  pending = false,
  onConfirm,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  confirmLabel: string;
  confirmKind?: BtnKind;
  disabled?: boolean;
  pending?: boolean;
  onConfirm: () => void;
  children?: ReactNode;
}) {
  // Stable per-mount id for aria-labelledby.
  const [titleId] = useState(() => `admin-modal-${++_modalSeq}`);
  return (
    <Modal open={open} onClose={onClose} labelledBy={titleId}>
      <div
        className="w-[440px] max-w-[92vw] border border-hairline-strong bg-tier-1 flex flex-col"
        style={{ borderRadius: 4 }}
      >
        <div className="px-3.5 py-2.5 border-b border-hairline">
          <h2
            id={titleId}
            className="text-tiny uppercase tracking-label-up text-fg-secondary m-0 font-normal"
          >
            {title}
          </h2>
        </div>
        <div className="px-3.5 py-3 flex flex-col gap-3">
          {description && (
            <p className="text-tiny text-fg-secondary m-0 leading-5">{description}</p>
          )}
          {children}
          <div className="flex justify-end gap-2 pt-1">
            <Btn kind="ghost" onClick={onClose}>
              Cancel
            </Btn>
            <Btn
              kind={confirmKind}
              disabled={disabled || pending}
              onClick={onConfirm}
            >
              {pending ? "Working…" : confirmLabel}
            </Btn>
          </div>
        </div>
      </div>
    </Modal>
  );
}

/** Labelled field wrapper (SupportPage's Field, shared). */
export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 11, letterSpacing: "0.08em" }}
      >
        {label}
      </span>
      {children}
    </label>
  );
}

export const INPUT_CLS =
  "h-8 px-2 bg-tier-2 border border-tier-3 rounded-btn text-fg-primary placeholder:text-fg-tertiary focus:border-amber focus:outline-none";
export const TEXTAREA_CLS =
  "px-2 py-1.5 bg-tier-2 border border-tier-3 rounded-btn text-fg-primary placeholder:text-fg-tertiary focus:border-amber focus:outline-none resize-y";
export const SELECT_CLS =
  "h-8 px-1.5 bg-tier-2 border border-tier-3 rounded-btn text-fg-primary focus:border-amber focus:outline-none";

// -- formatting --------------------------------------------------------------------------

const money = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export const fmtMoney = (n: number): string => money.format(n);

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}
