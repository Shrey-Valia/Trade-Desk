import { useMemo, useState } from "react";

import { TradeDeskLogo } from "@/components/branding/TradeDeskLogo";
import { useJournalAnalytics } from "@/hooks/useJournalAnalytics";
import type {
  AnalyticsResponse,
  DteBucket,
  KpiBlock,
  MistakeBucket,
  StrategyBucket,
} from "@/types/analytics";
import { STRATEGY_LABELS } from "@/types/journal";

import { EquityChart } from "@/components/analytics/EquityChart";

type PaperFilter = "all" | "paper" | "live";

/**
 * Trade Desk analytics — cross-trade aggregations over the journal.
 *
 * Layout per the spec:
 *   - Top toolbar matches POSITIONS (wordmark + mode toggle + filters)
 *   - KPI strip top (the headline numbers)
 *   - By-strategy table dominates (the edge-finding view)
 *   - DTE breakdown + mistake-cost side-by-side
 *   - Equity curve full-width at the bottom
 *
 * All numbers come from /api/analytics — no math happens here. The
 * page composes filters at the top and passes them through.
 */
export function AnalyticsPage() {
  const [paperFilter, setPaperFilter] = useState<PaperFilter>("all");
  const [strategyFilter, setStrategyFilter] = useState<string>("");

  const filters = useMemo(
    () => ({
      paper: paperFilter === "all" ? null : paperFilter === "paper",
      strategy: strategyFilter || null,
    }),
    [paperFilter, strategyFilter],
  );

  const { data, isLoading, isError, error } = useJournalAnalytics(filters);

  return (
    <div className="flex flex-col h-full min-h-0 bg-tier-0">
      <Toolbar
        paperFilter={paperFilter}
        onPaperChange={setPaperFilter}
        strategyFilter={strategyFilter}
        onStrategyChange={setStrategyFilter}
        availableStrategies={data?.by_strategy.map((s) => s.strategy) ?? []}
        loading={isLoading}
      />
      <main className="flex-1 min-h-0 overflow-y-auto">
        {isError ? (
          <ErrorState message={(error as Error)?.message ?? "Failed to load analytics"} />
        ) : !data ? (
          <LoadingState />
        ) : (
          <AnalyticsBody data={data} />
        )}
      </main>
    </div>
  );
}

function Toolbar({
  paperFilter,
  onPaperChange,
  strategyFilter,
  onStrategyChange,
  availableStrategies,
  loading,
}: {
  paperFilter: PaperFilter;
  onPaperChange: (f: PaperFilter) => void;
  strategyFilter: string;
  onStrategyChange: (s: string) => void;
  availableStrategies: string[];
  loading: boolean;
}) {
  return (
    <header
      className="flex items-center gap-6 border-b border-hairline bg-tier-0 px-4 shrink-0"
      style={{ height: 36 }}
    >
      <TradeDeskLogo size="compact" />
      <span className="text-xs2 uppercase tracking-label-up text-fg-secondary">
        Analytics
      </span>
      <div className="flex items-center gap-1 ml-2">
        {(["all", "paper", "live"] as PaperFilter[]).map((opt) => (
          <button
            key={opt}
            type="button"
            onClick={() => onPaperChange(opt)}
            className={[
              "h-6 px-2 text-tiny uppercase tracking-label-up border",
              paperFilter === opt
                ? "border-amber text-amber bg-tier-1"
                : "border-hairline text-fg-tertiary hover:bg-tier-2",
            ].join(" ")}
            style={{ borderRadius: 0 }}
          >
            {opt}
          </button>
        ))}
      </div>
      <select
        value={strategyFilter}
        onChange={(e) => onStrategyChange(e.target.value)}
        className="h-6 px-1 text-tiny bg-tier-1 border border-hairline text-fg-primary"
        style={{ borderRadius: 0 }}
      >
        <option value="">All strategies</option>
        {availableStrategies.map((s) => (
          <option key={s} value={s}>
            {STRATEGY_LABELS[s] ?? s}
          </option>
        ))}
      </select>
      {loading && (
        <span className="text-tiny text-fg-tertiary">refreshing…</span>
      )}
    </header>
  );
}

function AnalyticsBody({ data }: { data: AnalyticsResponse }) {
  return (
    <div className="flex flex-col gap-3 p-3">
      <KpiStrip kpis={data.kpis} />
      <ByStrategyTable rows={data.by_strategy} />
      <div className="grid grid-cols-2 gap-3">
        <ByDteBlock rows={data.by_dte} />
        <ByMistakeBlock rows={data.by_mistake} />
      </div>
      <EquitySection
        equity={data.equity}
        title="Equity curve"
        subtitle="Cumulative realized P&L over time"
      />
    </div>
  );
}

// -- KPI strip ---------------------------------------------------------------

function KpiStrip({ kpis }: { kpis: KpiBlock }) {
  return (
    <section className="border border-hairline bg-tier-0">
      <div className="px-3 py-1.5 border-b border-hairline">
        <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
          Headline
        </span>
      </div>
      <div className="grid grid-cols-7 divide-x divide-hairline">
        <Kpi label="Trades">
          <span className="text-display font-medium text-fg-primary tabular-nums">
            {kpis.closed_trades}
          </span>
          <span className="text-tiny text-fg-tertiary tabular-nums">
            of {kpis.total_trades} ({kpis.open_trades} open)
          </span>
        </Kpi>
        <Kpi label="Win rate">
          <span className="text-display font-medium tabular-nums text-fg-primary">
            {kpis.win_rate == null ? "—" : `${(kpis.win_rate * 100).toFixed(0)}%`}
          </span>
        </Kpi>
        <Kpi label="Net P&L">
          <span className={`text-display font-medium tabular-nums ${pnlClass(kpis.net_pnl)}`}>
            {formatDollar(kpis.net_pnl)}
          </span>
        </Kpi>
        <Kpi label="Profit factor">
          <span className="text-display font-medium tabular-nums text-fg-primary">
            {kpis.profit_factor == null ? "—" : kpis.profit_factor.toFixed(2)}
          </span>
        </Kpi>
        <Kpi label="Avg winner">
          <span className="text-medium font-medium tabular-nums text-bullish">
            {kpis.avg_winner == null ? "—" : formatDollar(kpis.avg_winner)}
          </span>
        </Kpi>
        <Kpi label="Avg loser">
          <span className="text-medium font-medium tabular-nums text-bearish">
            {kpis.avg_loser == null ? "—" : formatDollar(kpis.avg_loser)}
          </span>
        </Kpi>
        <Kpi label="Expectancy">
          <span className={`text-medium font-medium tabular-nums ${pnlClass(kpis.expectancy ?? 0)}`}>
            {kpis.expectancy == null ? "—" : formatDollar(kpis.expectancy)}
          </span>
          {kpis.avg_r != null && (
            <span className="text-tiny text-fg-tertiary tabular-nums">
              avg {kpis.avg_r >= 0 ? "+" : ""}
              {kpis.avg_r.toFixed(2)}R
            </span>
          )}
        </Kpi>
      </div>
    </section>
  );
}

function Kpi({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col px-3 py-2 gap-0.5">
      <span className="text-tiny uppercase tracking-label-up text-fg-tertiary" style={{ fontSize: 9 }}>
        {label}
      </span>
      {children}
    </div>
  );
}

// -- By strategy -------------------------------------------------------------

function ByStrategyTable({ rows }: { rows: StrategyBucket[] }) {
  return (
    <section className="border border-hairline bg-tier-0">
      <div className="px-3 py-1.5 border-b border-hairline">
        <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
          By strategy
        </span>
        <span className="ml-2 text-tiny text-fg-tertiary normal-case">
          edge-finding view — sorted by net P&L
        </span>
      </div>
      {rows.length === 0 ? (
        <EmptyRow label="No closed trades match the current filters." />
      ) : (
        <table className="w-full text-tiny tabular-nums">
          <thead>
            <tr className="text-fg-secondary uppercase tracking-label-up">
              <Th className="text-left">Strategy</Th>
              <Th className="text-right">Trades</Th>
              <Th className="text-right">Closed</Th>
              <Th className="text-right">Win rate</Th>
              <Th className="text-right">Net P&L</Th>
              <Th className="text-right">Avg P&L</Th>
              <Th className="text-right">PF</Th>
              <Th className="text-right">Avg R</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.strategy} className="border-t border-hairline hover:bg-tier-1">
                <Td className="text-left text-fg-primary">
                  {STRATEGY_LABELS[r.strategy] ?? r.strategy}
                </Td>
                <Td className="text-right text-fg-secondary">{r.trades}</Td>
                <Td className="text-right text-fg-secondary">{r.closed}</Td>
                <Td className="text-right text-fg-primary">
                  {r.win_rate == null ? "—" : `${(r.win_rate * 100).toFixed(0)}%`}
                </Td>
                <Td className={`text-right ${pnlClass(r.net_pnl)}`}>
                  {formatDollar(r.net_pnl)}
                </Td>
                <Td className={`text-right ${pnlClass(r.avg_pnl ?? null)}`}>
                  {r.avg_pnl == null ? "—" : formatDollar(r.avg_pnl)}
                </Td>
                <Td className="text-right text-fg-primary">
                  {r.profit_factor == null ? "—" : r.profit_factor.toFixed(2)}
                </Td>
                <Td className={`text-right ${pnlClass(r.avg_r ?? null)}`}>
                  {r.avg_r == null ? "—" : formatR(r.avg_r)}
                </Td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

// -- DTE bar block -----------------------------------------------------------

function ByDteBlock({ rows }: { rows: DteBucket[] }) {
  const maxAbs = Math.max(1, ...rows.map((r) => Math.abs(r.net_pnl)));
  return (
    <section className="border border-hairline bg-tier-0">
      <div className="px-3 py-1.5 border-b border-hairline">
        <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
          By DTE at entry
        </span>
        <span className="ml-2 text-tiny text-fg-tertiary normal-case">
          which time horizon works for you
        </span>
      </div>
      <table className="w-full text-tiny tabular-nums">
        <thead>
          <tr className="text-fg-secondary uppercase tracking-label-up">
            <Th className="text-left">Bucket</Th>
            <Th className="text-right">N</Th>
            <Th className="text-right">Win</Th>
            <Th className="text-right">Avg</Th>
            <Th className="text-right">Net</Th>
            <Th />
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const widthPct = (Math.abs(r.net_pnl) / maxAbs) * 100;
            const barColor = r.net_pnl >= 0 ? "bg-bullish" : "bg-bearish";
            return (
              <tr key={r.label} className="border-t border-hairline">
                <Td className="text-left text-fg-primary">{r.label}d</Td>
                <Td className="text-right text-fg-secondary">{r.trades}</Td>
                <Td className="text-right text-fg-primary">
                  {r.win_rate == null ? "—" : `${(r.win_rate * 100).toFixed(0)}%`}
                </Td>
                <Td className={`text-right ${pnlClass(r.avg_pnl ?? null)}`}>
                  {r.avg_pnl == null ? "—" : formatDollar(r.avg_pnl)}
                </Td>
                <Td className={`text-right ${pnlClass(r.net_pnl)}`}>
                  {formatDollar(r.net_pnl)}
                </Td>
                <Td>
                  <div className="h-1.5 bg-tier-1 relative" style={{ minWidth: 60 }}>
                    {r.net_pnl !== 0 && (
                      <div
                        className={`absolute top-0 bottom-0 left-0 ${barColor}`}
                        style={{ width: `${widthPct}%`, opacity: 0.6 }}
                      />
                    )}
                  </div>
                </Td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

// -- Mistake cost ------------------------------------------------------------

function ByMistakeBlock({ rows }: { rows: MistakeBucket[] }) {
  const maxAbs = Math.max(1, ...rows.map((r) => Math.abs(r.net_pnl)));
  return (
    <section className="border border-hairline bg-tier-0">
      <div className="px-3 py-1.5 border-b border-hairline">
        <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
          Mistake cost
        </span>
        <span className="ml-2 text-tiny text-fg-tertiary normal-case">
          most-costly behaviors first
        </span>
      </div>
      {rows.length === 0 ? (
        <EmptyRow label="No mistake tags on closed trades." />
      ) : (
        <table className="w-full text-tiny tabular-nums">
          <thead>
            <tr className="text-fg-secondary uppercase tracking-label-up">
              <Th className="text-left">Tag</Th>
              <Th className="text-right">N</Th>
              <Th className="text-right">Net P&L</Th>
              <Th className="text-right">R</Th>
              <Th />
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const widthPct = (Math.abs(r.net_pnl) / maxAbs) * 100;
              return (
                <tr key={r.tag} className="border-t border-hairline">
                  <Td className="text-left text-fg-primary">{r.tag}</Td>
                  <Td className="text-right text-fg-secondary">{r.trades}</Td>
                  <Td className={`text-right ${pnlClass(r.net_pnl)}`}>
                    {formatDollar(r.net_pnl)}
                  </Td>
                  <Td className={`text-right ${pnlClass(r.total_r ?? null)}`}>
                    {r.total_r == null ? "—" : formatR(r.total_r)}
                  </Td>
                  <Td>
                    <div className="h-1.5 bg-tier-1 relative" style={{ minWidth: 60 }}>
                      <div
                        className="absolute top-0 bottom-0 left-0 bg-bearish"
                        style={{ width: `${widthPct}%`, opacity: 0.6 }}
                      />
                    </div>
                  </Td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}

// -- Equity curve ------------------------------------------------------------

function EquitySection({
  equity,
  title,
  subtitle,
}: {
  equity: AnalyticsResponse["equity"];
  title: string;
  subtitle: string;
}) {
  return (
    <section className="border border-hairline bg-tier-0">
      <div className="flex items-baseline justify-between px-3 py-1.5 border-b border-hairline">
        <span>
          <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
            {title}
          </span>
          <span className="ml-2 text-tiny text-fg-tertiary normal-case">{subtitle}</span>
        </span>
        <span className="text-tiny text-fg-tertiary tabular-nums">
          Final {formatDollar(equity.final_pnl)} · Peak {formatDollar(equity.peak_pnl)} · Max DD{" "}
          <span className="text-bearish">−{formatDollar(equity.max_drawdown).replace("−", "")}</span>
        </span>
      </div>
      <div style={{ height: 240 }}>
        <EquityChart points={equity.points} />
      </div>
    </section>
  );
}

// -- Helpers -----------------------------------------------------------------

function Th({ children, className }: { children?: React.ReactNode; className?: string }) {
  return (
    <th
      className={`px-2 py-1 font-normal text-tiny tracking-label-up ${className ?? ""}`}
    >
      {children}
    </th>
  );
}

function Td({ children, className }: { children?: React.ReactNode; className?: string }) {
  return <td className={`px-2 py-1 ${className ?? ""}`}>{children}</td>;
}

function EmptyRow({ label }: { label: string }) {
  return (
    <div className="px-3 py-6 text-tiny text-fg-tertiary text-center">{label}</div>
  );
}

function LoadingState() {
  return (
    <div className="p-3 text-tiny text-fg-tertiary">Loading analytics…</div>
  );
}

function ErrorState({ message }: { message: string }) {
  return <div className="p-3 text-tiny text-bearish">{message}</div>;
}

function formatDollar(value: number): string {
  if (!Number.isFinite(value)) return "—";
  const sign = value < 0 ? "−" : "";
  return `${sign}$${Math.abs(value).toFixed(2)}`;
}

function formatR(r: number): string {
  const sign = r < 0 ? "−" : r > 0 ? "+" : "";
  return `${sign}${Math.abs(r).toFixed(2)}R`;
}

function pnlClass(v: number | null): string {
  if (v == null) return "text-fg-tertiary";
  if (v > 0) return "text-bullish";
  if (v < 0) return "text-bearish";
  return "text-fg-secondary";
}
