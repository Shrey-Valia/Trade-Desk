import { useQuery } from "@tanstack/react-query";

import { LoadError } from "@/components/ui/LoadError";
import { adminKeys, fetchAdminMetrics } from "@/lib/adminApi";

import { AdminPreflight } from "./AdminPreflight";

import {
  fmtMoney,
  NUM_CLS,
  Panel,
  StatTile,
  TABLE_CLS,
  TABLE_FONT,
  TD_CLS,
  TH_CLS,
} from "./adminUi";

/**
 * Overview — the operator's morning glance: MRR, user counts, payout
 * liability, open tickets, and the per-tier combine ledger with pass
 * rates. Pure read; no chart library — dense tiles + one table.
 */
export function AdminOverview() {
  const metrics = useQuery({
    queryKey: adminKeys.metrics,
    queryFn: fetchAdminMetrics,
    staleTime: 15_000,
    refetchInterval: 60_000,
  });

  // The preflight panel renders above the metrics and OUTSIDE their loading
  // and error branches: a deployment whose metrics query is failing is
  // exactly when a configuration finding is most worth reading.
  if (metrics.isPending) {
    return (
      <div className="flex flex-col gap-3.5">
        <AdminPreflight />
        <div className="px-1 py-6 text-tiny text-fg-tertiary-2">
          Loading metrics…
        </div>
      </div>
    );
  }
  if (metrics.isError) {
    return (
      <div className="flex flex-col gap-3.5">
        <AdminPreflight />
        <LoadError subject="platform metrics" onRetry={metrics.refetch} />
      </div>
    );
  }
  const m = metrics.data;
  const pendingLiability = m.payout_liability["requested_pending"] ?? 0;
  const approvedUnpaid = m.payout_liability["approved_unpaid"] ?? 0;
  const tiers = Object.keys(m.combines).sort();

  return (
    <div className="flex flex-col gap-3.5">
      <AdminPreflight />
      <div className="grid gap-2 grid-cols-2 sm:grid-cols-3 xl:grid-cols-6">
        <StatTile label="MRR" value={fmtMoney(m.mrr)} tone="amber" hint="active combines × monthly price" />
        <StatTile label="Users" value={m.users_total.toLocaleString("en-US")} />
        <StatTile
          label="New · 30d"
          value={m.users_last_30d.toLocaleString("en-US")}
        />
        <StatTile
          label="Payout liability"
          value={fmtMoney(pendingLiability)}
          tone={pendingLiability > 0 ? "warning" : undefined}
          hint="requested + in review + held"
        />
        <StatTile
          label="Approved · unpaid"
          value={fmtMoney(approvedUnpaid)}
          tone={approvedUnpaid > 0 ? "bearish" : undefined}
          hint="awaiting mark-paid"
        />
        <StatTile
          label="Open tickets"
          value={m.tickets_open.toLocaleString("en-US")}
          tone={m.tickets_open > 0 ? "amber" : undefined}
        />
      </div>

      <Panel label="Combines by tier">
        {tiers.length === 0 ? (
          <div className="px-3 py-4 text-tiny text-fg-tertiary-2">
            No combines yet.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className={TABLE_CLS} style={TABLE_FONT}>
              <thead>
                <tr>
                  <th className={TH_CLS}>Tier</th>
                  <th className={TH_CLS}>By status</th>
                  <th className={TH_CLS}>By outcome</th>
                  <th className={`${TH_CLS} text-right`}>Pass rate</th>
                </tr>
              </thead>
              <tbody>
                {tiers.map((tier) => {
                  const bucket = m.combines[tier];
                  const rate = m.pass_rate[tier];
                  return (
                    <tr key={tier} className="hover:bg-tier-2">
                      <td className={`${TD_CLS} uppercase text-fg-primary font-medium`}>
                        {tier}
                      </td>
                      <td className={TD_CLS}>
                        <CountList counts={bucket.by_status} />
                      </td>
                      <td className={TD_CLS}>
                        <CountList counts={bucket.by_outcome} />
                      </td>
                      <td className={`${TD_CLS} ${NUM_CLS} text-right`}>
                        {rate == null ? (
                          <span className="text-fg-tertiary-2">—</span>
                        ) : (
                          <span
                            className={rate >= 0.5 ? "text-bullish" : "text-fg-primary"}
                          >
                            {(rate * 100).toFixed(1)}%
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}

/** {"active": 3, "archived": 1} → "active 3 · archived 1", numeric parts
 *  tabular so columns of these stay scannable. */
function CountList({ counts }: { counts: Record<string, number> }) {
  const keys = Object.keys(counts).sort();
  if (keys.length === 0) return <span className="text-fg-tertiary-2">—</span>;
  return (
    <span className="inline-flex gap-2 flex-wrap">
      {keys.map((k) => (
        <span key={k} className="whitespace-nowrap">
          <span className="text-fg-tertiary-2">{k}</span>{" "}
          <span className={`${NUM_CLS} text-fg-primary`}>{counts[k]}</span>
        </span>
      ))}
    </span>
  );
}
