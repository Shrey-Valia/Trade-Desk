import { Link } from "react-router-dom";

import { PageHeader } from "@/components/layout/PageHeader";
import { EmptyState } from "@/components/ui/EmptyState";
import { MetricPill } from "@/components/ui/MetricPill";
import { useActivateAccount, useCombines, useRequestPayout } from "@/hooks/useCombines";
import { splitPct, splitTokenFromValue } from "@/lib/pricing";
import type { CombineOut } from "@/types/combine";

/**
 * /payouts — funded-account payouts (Topstep's Payouts tab). Lists every
 * FUNDED combine with its available payout (the trader's chosen 80/20 or
 * 50/50 split of realized profit, net of prior requests) and a request
 * button. Accounts on the activation path must pay the one-time $149 fee
 * first. Simulated: requesting logs an event and moves no money.
 */
export function PayoutsPage() {
  const { data, isPending } = useCombines();
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
  const available = combine.payout_eligible;
  const needsActivation = combine.activation_required;
  const splitText = `${splitPct(splitTokenFromValue(combine.profit_split))}%`;
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
      </div>
      <Figure label="Realized profit" value={formatDollar(Math.max(0, combine.realized_pnl))} />
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
          disabled={available <= 0 || payout.isPending}
          onClick={() => payout.mutate(combine.id)}
          className="h-8 px-3 text-tiny uppercase tracking-label-up border border-bullish text-bullish hover:bg-tier-2 disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
          style={{ borderRadius: 0 }}
        >
          {payout.isPending ? "…" : "Request payout"}
        </button>
      )}
    </div>
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
