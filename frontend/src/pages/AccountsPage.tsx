import { Link } from "react-router-dom";

import {
  CombineCardsGrid,
  cushionAlarmed,
  mllCushion,
} from "@/components/combines/CombineCards";
import { CombineSwitcher } from "@/components/combines/CombineSwitcher";
import { CopyTradingPanel } from "@/components/combines/CopyTradingPanel";
import { PageHeader } from "@/components/layout/PageHeader";
import { LoadError } from "@/components/ui/LoadError";
import { MetricPill } from "@/components/ui/MetricPill";
import { useCombines } from "@/hooks/useCombines";

/**
 * /accounts — the dedicated all-accounts view (Topstep's "Accounts" tab).
 * Lists every combine the user owns, active and archived, with the same
 * cards as the dashboard plus a roll-up strip across non-archived
 * accounts — including the worst MLL cushion, because copy-trading
 * followers take trades the user isn't watching. Account switching /
 * rename / archive happen on the cards.
 */
export function AccountsPage() {
  const { data, isPending, isError, refetch } = useCombines();
  const all = data?.combines ?? [];
  const active = all.filter((c) => c.status !== "archived");
  const archived = all.filter((c) => c.status === "archived");
  const totalBalance = active.reduce((s, c) => s + c.balance, 0);
  const totalClosed = active.reduce((s, c) => s + c.realized_pnl, 0);
  // Worst room-above-the-floor across surviving accounts — the account a
  // copy-trade follower can quietly blow up while the lead looks fine.
  const alive = active.filter((c) => c.outcome !== "failed");
  const worstCushioned = alive.reduce<(typeof alive)[number] | null>(
    (worst, c) =>
      worst == null || mllCushion(c) < mllCushion(worst) ? c : worst,
    null,
  );

  return (
    <div className="flex flex-col h-full min-h-0 bg-tier-0">
      <PageHeader
        title="Accounts"
        subtitle={
          data
            ? `${data.slots_used} of ${data.slots_total} combine slots used`
            : undefined
        }
      />
      <main className="flex-1 min-h-0 overflow-y-auto border-t border-hairline">
        <div className="mx-auto w-full max-w-[1280px] p-3.5 flex flex-col gap-3.5">
          {/* Roll-up across active accounts + new-combine CTA. */}
          <div className="flex items-center gap-3 flex-wrap">
            <CombineSwitcher />
            <MetricPill label="OPEN ACCOUNTS" value={String(active.length)} />
            <MetricPill label="TOTAL BALANCE" value={formatDollar(totalBalance)} />
            <MetricPill
              label="TOTAL CLOSED P&L"
              value={formatSigned(totalClosed)}
              signed={totalClosed}
            />
            {worstCushioned && (
              <MetricPill
                label="WORST MLL CUSHION"
                value={formatDollar(mllCushion(worstCushioned))}
                sub={worstCushioned.name}
                tone={cushionAlarmed(worstCushioned) ? "bearish" : "default"}
                title="The account closest to its MLL floor — watch it even when you're trading another (copy-trade followers fail on their own floors)."
              />
            )}
            <Link
              to="/combines/new"
              className="ml-auto h-8 px-3 inline-flex items-center text-tiny uppercase tracking-label-up bg-amber text-tier-0 hover:opacity-90 font-medium"
              style={{ borderRadius: 0 }}
            >
              Start a Trading Combine
            </Link>
          </div>

          {isPending ? (
            <div className="px-1 py-6 text-tiny text-fg-tertiary-2">
              Loading accounts…
            </div>
          ) : isError ? (
            <LoadError subject="your accounts" onRetry={refetch} />
          ) : all.length === 0 ? (
            <div className="px-1 py-10 text-center text-tiny text-fg-tertiary-2">
              No accounts yet — start a Trading Combine to get going.
            </div>
          ) : (
            <>
              <Section title="Open" count={active.length}>
                {active.length > 0 ? (
                  <CombineCardsGrid
                    combines={active}
                    activeCombineId={data?.active_combine_id}
                    leadCombineId={data?.copy_lead_combine_id}
                  />
                ) : (
                  <Empty text="No open accounts — start one." />
                )}
              </Section>
              {archived.length > 0 && (
                <Section title="Archived" count={archived.length}>
                  <CombineCardsGrid
                    combines={archived}
                    activeCombineId={data?.active_combine_id}
                    leadCombineId={data?.copy_lead_combine_id}
                  />
                </Section>
              )}
              <div
                className="border border-hairline-strong bg-tier-1"
                style={{ borderRadius: 4 }}
              >
                <div className="px-3.5 py-3">
                  <CopyTradingPanel />
                </div>
              </div>
            </>
          )}
        </div>
      </main>
    </div>
  );
}

function Section({
  title,
  count,
  children,
}: {
  title: string;
  count: number;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline gap-2">
        <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
          {title}
        </span>
        <span className="text-tiny text-fg-tertiary-2 tabular-nums">{count}</span>
      </div>
      {children}
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="px-1 py-6 text-tiny text-fg-tertiary-2">{text}</div>
  );
}

function formatDollar(v: number): string {
  if (!Number.isFinite(v)) return "—";
  return `$${v.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function formatSigned(v: number): string {
  if (!Number.isFinite(v)) return "$0.00";
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  return `${sign}$${Math.abs(v).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}
