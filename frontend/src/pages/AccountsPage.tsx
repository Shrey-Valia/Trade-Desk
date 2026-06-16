import { Link } from "react-router-dom";

import { CombineCardsGrid } from "@/components/combines/CombineCards";
import { PageHeader } from "@/components/layout/PageHeader";
import { MetricPill } from "@/components/ui/MetricPill";
import { useCombines } from "@/hooks/useCombines";

/**
 * /accounts — the dedicated all-accounts view (Topstep's "Accounts" tab).
 * Lists every combine the user owns, active and archived, with the same
 * cards as the dashboard plus a roll-up strip across non-archived
 * accounts. Account switching / rename / archive happen on the cards.
 */
export function AccountsPage() {
  const { data, isPending } = useCombines();
  const all = data?.combines ?? [];
  const active = all.filter((c) => c.status !== "archived");
  const archived = all.filter((c) => c.status === "archived");
  const totalBalance = active.reduce((s, c) => s + c.balance, 0);
  const totalClosed = active.reduce((s, c) => s + c.realized_pnl, 0);

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
        <div className="p-3.5 flex flex-col gap-3.5">
          {/* Roll-up across active accounts + new-combine CTA. */}
          <div className="flex items-center gap-3 flex-wrap">
            <MetricPill label="ACTIVE ACCOUNTS" value={String(active.length)} />
            <MetricPill label="TOTAL BALANCE" value={formatDollar(totalBalance)} />
            <MetricPill
              label="TOTAL CLOSED P&L"
              value={formatSigned(totalClosed)}
              signed={totalClosed}
            />
            <Link
              to="/combines/new"
              className="ml-auto h-8 px-3 inline-flex items-center text-tiny uppercase tracking-label-up border border-amber text-amber bg-tier-1 hover:bg-tier-2 font-medium"
              style={{ borderRadius: 0 }}
            >
              Start a Trading Combine
            </Link>
          </div>

          {isPending ? (
            <div className="px-1 py-6 text-tiny text-fg-tertiary-2">
              Loading accounts…
            </div>
          ) : all.length === 0 ? (
            <div className="px-1 py-10 text-center text-tiny text-fg-tertiary-2">
              No accounts yet — start a Trading Combine to get going.
            </div>
          ) : (
            <>
              <Section title="Active" count={active.length}>
                {active.length > 0 ? (
                  <CombineCardsGrid
                    combines={active}
                    activeCombineId={data?.active_combine_id}
                  />
                ) : (
                  <Empty text="No active accounts — activate or purchase one." />
                )}
              </Section>
              {archived.length > 0 && (
                <Section title="Archived" count={archived.length}>
                  <CombineCardsGrid
                    combines={archived}
                    activeCombineId={data?.active_combine_id}
                  />
                </Section>
              )}
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
