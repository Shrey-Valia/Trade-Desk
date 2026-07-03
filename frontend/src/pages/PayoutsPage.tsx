import { useState } from "react";
import { Link } from "react-router-dom";

import { PageHeader } from "@/components/layout/PageHeader";
import { Modal } from "@/components/ui/Modal";
import { EmptyState } from "@/components/ui/EmptyState";
import { LoadError } from "@/components/ui/LoadError";
import { MetricPill } from "@/components/ui/MetricPill";
import {
  useActivateAccount,
  useCombineEvents,
  useCombines,
  useRequestPayout,
} from "@/hooks/useCombines";
import { splitPct, splitTokenFromValue } from "@/lib/pricing";
import type { CombineEvent, CombineOut } from "@/types/combine";

/**
 * /payouts — funded-account payouts (Topstep's Payouts tab). Lists every
 * FUNDED combine with its available payout (the trader's chosen 80/20 or
 * 50/50 split of realized profit, net of prior requests), the split math
 * spelled out, and a request flow: pick an amount (defaults to the max
 * eligible), confirm, and the backend's payout gates (minimum, winning-day
 * count, 24h spacing, MLL buffer) answer with a 409 detail we surface
 * verbatim. A ledger of prior payout events sits below. Accounts on the
 * activation path must pay the one-time $149 fee first. Simulated:
 * requesting logs an event and moves no money.
 */
export function PayoutsPage() {
  const { data, isPending, isError, refetch } = useCombines();
  const all = data?.combines ?? [];
  const funded = all.filter((c) => c.funded && c.status !== "archived");
  const totalAvailable = funded.reduce((s, c) => s + c.payout_eligible, 0);
  const totalRequested = funded.reduce((s, c) => s + c.payout_requested, 0);

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
                <PayoutRow key={c.id} combine={c} />
              ))}
            </div>
          )}

          <PayoutLedger />

          <span className="text-tiny text-fg-tertiary-2 leading-relaxed">
            Payouts are simulated — requesting records the event and reduces
            the available figure, but moves no real money. Your split (80/20 or
            50/50) and any activation fee were set when you bought the combine.
          </span>
        </div>
      </main>
    </div>
  );
}

function PayoutRow({ combine }: { combine: CombineOut }) {
  const payout = useRequestPayout();
  const activate = useActivateAccount();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const available = combine.payout_eligible;
  const needsActivation = combine.activation_required;
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
          onClick={() => activate.mutate(combine.id)}
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
        <button
          type="button"
          disabled={available <= 0}
          onClick={() => {
            payout.reset();
            setConfirmOpen(true);
          }}
          className="h-8 px-3 text-tiny uppercase tracking-label-up border border-bullish text-bullish hover:bg-tier-2 disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
          style={{ borderRadius: 0 }}
        >
          Request payout
        </button>
      )}
      {confirmOpen && (
        <PayoutConfirmDialog
          combine={combine}
          payout={payout}
          onClose={() => setConfirmOpen(false)}
        />
      )}
    </div>
  );
}

/**
 * Confirm step for a payout request: pick the amount (defaults to the max
 * eligible) and confirm. A backend 409 — the minimum, winning-day, 24h, or
 * MLL-buffer gate — renders its detail verbatim so the trader knows the
 * exact rule that blocked the request.
 */
function PayoutConfirmDialog({
  combine,
  payout,
  onClose,
}: {
  combine: CombineOut;
  payout: ReturnType<typeof useRequestPayout>;
  onClose: () => void;
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
            { onSuccess: onClose },
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

/** Prior payout requests across all accounts — date, account, amount. Fed
 *  by the same events endpoint the dashboard feed uses, filtered to payout
 *  events, so the ledger and the toasts can never disagree. */
function PayoutLedger() {
  const { data, isPending } = useCombineEvents();
  const payouts = (data ?? []).filter((e) => e.type === "payout");

  return (
    <div className="border border-hairline-strong bg-tier-1" style={{ borderRadius: 4 }}>
      <div className="flex items-baseline justify-between px-3 py-1.5 border-b border-hairline">
        <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
          Payout history
        </span>
        <span className="uppercase tracking-label-up text-fg-tertiary-2 tabular-nums" style={{ fontSize: 11 }}>
          {payouts.length} request{payouts.length === 1 ? "" : "s"}
        </span>
      </div>
      {isPending ? (
        <div className="px-3 py-3 text-tiny text-fg-tertiary-2">Loading…</div>
      ) : payouts.length === 0 ? (
        <div className="px-3 py-3 text-tiny text-fg-tertiary-2">
          No payouts requested yet — your requests will show up here.
        </div>
      ) : (
        <ul className="divide-y divide-hairline">
          {payouts.map((e) => (
            <LedgerRow key={e.id} event={e} />
          ))}
        </ul>
      )}
    </div>
  );
}

function LedgerRow({ event }: { event: CombineEvent }) {
  return (
    <li className="flex items-baseline gap-3 px-3 py-1.5 tabular-nums">
      <span className="text-tiny text-fg-tertiary-2 shrink-0" style={{ minWidth: 84 }}>
        {formatDate(event.created_at)}
      </span>
      <span className="text-tiny text-fg-secondary truncate flex-1">
        {event.combine_name ?? `Combine #${event.combine_id}`}
      </span>
      <span className="text-tiny text-bullish shrink-0">
        {event.amount != null ? formatDollar(event.amount) : "—"}
      </span>
    </li>
  );
}

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
