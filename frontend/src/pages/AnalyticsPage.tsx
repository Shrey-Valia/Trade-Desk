import { useMemo, useState } from "react";

import { EquityChart } from "@/components/analytics/EquityChart";
import { TradeDeskLogo } from "@/components/branding/TradeDeskLogo";
import { useAccountState } from "@/hooks/useAccountState";
import { useJournalAnalytics } from "@/hooks/useJournalAnalytics";
import type {
  AnalyticsResponse,
  KpiBlock,
  MistakeBucket,
  StrategyBucket,
} from "@/types/analytics";
import { STRATEGY_LABELS } from "@/types/journal";

type PaperFilter = "all" | "paper" | "live";
type Range = "Today" | "Week" | "Month" | "All";

/**
 * Trade Desk analytics — the understanding surface.
 *
 * Restyled to the design kit (ui_kits/analytics): a metric hero, a
 * prominent equity curve, and performance breakdowns. The header carries
 * a Today/Week/Month/All range, the active combine tier, and a paper/live
 * filter. All numbers come from /api/analytics — the page only composes
 * filters and presents the result.
 *
 * New design panels that need backend aggregations (by symbol, time of
 * day, day of week, streaks, risk vs MLL trail) land in Phase B.
 */
export function AnalyticsPage() {
  const [paperFilter, setPaperFilter] = useState<PaperFilter>("all");
  const [range, setRange] = useState<Range>("All");

  const filters = useMemo(() => {
    const { since, until } = rangeToDates(range);
    return {
      paper: paperFilter === "all" ? null : paperFilter === "paper",
      strategy: null,
      since,
      until,
    };
  }, [paperFilter, range]);

  const { data, isLoading, isError, error } = useJournalAnalytics(filters);
  const account = useAccountState();
  const tier = account.data?.active_tier ?? null;

  return (
    <div className="flex flex-col h-full min-h-0 bg-tier-0">
      <Toolbar
        tier={tier}
        range={range}
        onRangeChange={setRange}
        paperFilter={paperFilter}
        onPaperChange={setPaperFilter}
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
  tier,
  range,
  onRangeChange,
  paperFilter,
  onPaperChange,
  loading,
}: {
  tier: string | null;
  range: Range;
  onRangeChange: (r: Range) => void;
  paperFilter: PaperFilter;
  onPaperChange: (f: PaperFilter) => void;
  loading: boolean;
}) {
  return (
    <header
      className="flex items-center gap-5 border-b border-hairline bg-tier-0 px-4 shrink-0"
      style={{ height: 36 }}
    >
      <TradeDeskLogo size="compact" />
      <span className="text-xs2 uppercase tracking-label-up text-fg-secondary">Analytics</span>
      {tier && (
        <span
          className="inline-flex items-center h-6 px-2.5 border border-tier-3 bg-tier-2 text-fg-secondary uppercase tracking-label-up"
          style={{ fontSize: 10, borderRadius: 2 }}
        >
          {tier} Combine
        </span>
      )}
      {/* paper / live */}
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
      {/* range */}
      <div className="ml-auto flex items-stretch border border-hairline" style={{ borderRadius: 0 }}>
        {(["Today", "Week", "Month", "All"] as Range[]).map((r, i) => (
          <button
            key={r}
            type="button"
            onClick={() => onRangeChange(r)}
            className={[
              "h-6 px-3 text-tiny uppercase tracking-label-up",
              r === range
                ? "text-amber bg-tier-2"
                : "text-fg-tertiary-2 hover:bg-tier-2 hover:text-fg-secondary",
              i > 0 ? "border-l border-hairline" : "",
            ].join(" ")}
          >
            {r}
          </button>
        ))}
      </div>
      {loading && <span className="text-tiny text-fg-tertiary">refreshing…</span>}
    </header>
  );
}

function AnalyticsBody({ data }: { data: AnalyticsResponse }) {
  if (data.kpis.total_trades === 0) {
    return <NoTradesYet />;
  }
  return (
    <div className="flex flex-col gap-3.5 p-3.5">
      <MetricHero kpis={data.kpis} />
      <EquityPanel equity={data.equity} netSign={data.kpis.net_pnl} />
      <div className="grid grid-cols-2 gap-3.5 items-start">
        <ByStrategyPanel rows={data.by_strategy} />
        <MistakeCostPanel rows={data.by_mistake} />
      </div>
    </div>
  );
}

function NoTradesYet() {
  return (
    <div className="flex flex-col items-center justify-center h-full px-6 py-12 gap-3 text-center">
      <span
        className="uppercase tracking-label-up text-fg-secondary"
        style={{ fontSize: 9, letterSpacing: "0.08em" }}
      >
        No trades yet
      </span>
      <span className="text-medium text-fg-primary">
        Place your first paper trade to start tracking analytics.
      </span>
      <span className="text-tiny text-fg-tertiary max-w-md">
        Open a position from the option chain on the Chart view, or click
        + Log Trade to enter a trade manually. Closed trades populate the
        metric hero, strategy breakdown, mistake cost, and equity curve.
      </span>
    </div>
  );
}

// -- metric hero -------------------------------------------------------------

function MetricHero({ kpis }: { kpis: KpiBlock }) {
  const wins = kpis.win_rate == null ? 0 : Math.round(kpis.win_rate * kpis.closed_trades);
  const losses = kpis.closed_trades - wins;
  const wlRatio =
    kpis.avg_winner != null && kpis.avg_loser != null && kpis.avg_loser !== 0
      ? kpis.avg_winner / Math.abs(kpis.avg_loser)
      : null;

  return (
    <div className="grid gap-2.5" style={{ gridTemplateColumns: "repeat(6, minmax(0, 1fr))" }}>
      <Metric
        label="Net P&L"
        value={formatDollarSigned(kpis.net_pnl)}
        tone={kpis.net_pnl >= 0 ? "bull" : "bear"}
        sub={`${kpis.closed_trades} trade${kpis.closed_trades === 1 ? "" : "s"}`}
      />
      <Metric
        label="Win rate"
        value={kpis.win_rate == null ? "—" : `${(kpis.win_rate * 100).toFixed(0)}%`}
        sub={`${wins}W · ${losses}L`}
      />
      <Metric
        label="Profit factor"
        value={kpis.profit_factor == null ? "∞" : kpis.profit_factor.toFixed(2)}
        sub={kpis.profit_factor == null ? "no losers" : kpis.profit_factor >= 1 ? "net edge" : "bleeding"}
        subTone={kpis.profit_factor == null || kpis.profit_factor >= 1 ? "bull" : "bear"}
      />
      <Metric
        label="Avg win / loss"
        value={wlRatio == null ? "—" : `${wlRatio.toFixed(2)}×`}
        sub={`${kpis.avg_winner == null ? "—" : formatDollar(kpis.avg_winner)} / ${
          kpis.avg_loser == null ? "—" : formatDollar(kpis.avg_loser)
        }`}
      />
      <Metric
        label="Expectancy"
        value={kpis.expectancy == null ? "—" : formatDollarSigned(kpis.expectancy)}
        tone={kpis.expectancy != null && kpis.expectancy >= 0 ? "bull" : "bear"}
        sub={kpis.avg_r == null ? "per trade" : `${formatR(kpis.avg_r)} avg`}
      />
      <Metric
        label="Total trades"
        value={String(kpis.closed_trades)}
        sub={kpis.open_trades > 0 ? `${kpis.open_trades} open` : "all closed"}
      />
    </div>
  );
}

function Metric({
  label,
  value,
  tone,
  sub,
  subTone,
}: {
  label: string;
  value: string;
  tone?: "bull" | "bear";
  sub?: string;
  subTone?: "bull" | "bear";
}) {
  return (
    <div
      className="flex flex-col gap-1 bg-tier-1 border border-hairline px-3 py-2.5"
      style={{ borderRadius: 4 }}
    >
      <span className="uppercase tracking-label-up text-fg-tertiary-2" style={{ fontSize: 9 }}>
        {label}
      </span>
      <span
        className={`font-medium tabular-nums ${tone ? toneClass(tone) : "text-fg-primary"}`}
        style={{ fontSize: 22, lineHeight: "26px" }}
      >
        {value}
      </span>
      {sub && (
        <span className={`tabular-nums ${subTone ? toneClass(subTone) : "text-fg-tertiary"}`} style={{ fontSize: 10 }}>
          {sub}
        </span>
      )}
    </div>
  );
}

// -- equity curve ------------------------------------------------------------

function EquityPanel({
  equity,
  netSign,
}: {
  equity: AnalyticsResponse["equity"];
  netSign: number;
}) {
  return (
    <Panel>
      <PanelHead k="Equity Curve · cumulative P&L" r={`max drawdown ${formatDollar(equity.max_drawdown)}`} />
      <div className="p-3" style={{ height: 240 }}>
        <EquityChart points={equity.points} />
      </div>
      <div className="flex gap-4 px-3 pb-2.5 text-fg-tertiary-2" style={{ fontSize: 10 }}>
        <span className="inline-flex items-center gap-1.5">
          <span
            className={`inline-block ${netSign >= 0 ? "bg-bullish" : "bg-bearish"}`}
            style={{ width: 14, height: 2 }}
          />
          cumulative P&L
        </span>
        <span className="ml-auto tabular-nums">
          Final {formatDollarSigned(equity.final_pnl)} · Peak {formatDollarSigned(equity.peak_pnl)} · Max DD{" "}
          <span className="text-bearish">−{formatDollar(equity.max_drawdown).replace("−", "")}</span>
        </span>
      </div>
    </Panel>
  );
}

// -- by strategy (horizontal meters) -----------------------------------------

function ByStrategyPanel({ rows }: { rows: StrategyBucket[] }) {
  const closed = rows.filter((r) => r.closed > 0);
  const maxAbs = Math.max(1, ...closed.map((r) => Math.abs(r.net_pnl)));
  return (
    <Panel>
      <PanelHead k="By Strategy" r="net · win%" />
      {closed.length === 0 ? (
        <Empty label="No closed trades match the current filters." />
      ) : (
        <div className="flex flex-col gap-2.5 px-3 py-2.5">
          {closed.map((r) => (
            <MeterRow
              key={r.strategy}
              label={STRATEGY_LABELS[r.strategy] ?? r.strategy}
              net={r.net_pnl}
              maxAbs={maxAbs}
              right={
                <>
                  {formatDollarSigned(r.net_pnl)}
                  {r.win_rate != null && (
                    <span className="text-fg-tertiary-2"> · {(r.win_rate * 100).toFixed(0)}%</span>
                  )}
                </>
              }
            />
          ))}
        </div>
      )}
    </Panel>
  );
}

// -- mistake cost (kept as its own panel) ------------------------------------

function MistakeCostPanel({ rows }: { rows: MistakeBucket[] }) {
  const maxAbs = Math.max(1, ...rows.map((r) => Math.abs(r.net_pnl)));
  return (
    <Panel>
      <PanelHead k="Mistake Cost" r="most-costly first" />
      {rows.length === 0 ? (
        <Empty label="No mistake tags on closed trades." />
      ) : (
        <div className="flex flex-col gap-2.5 px-3 py-2.5">
          {rows.map((r) => (
            <MeterRow
              key={r.tag}
              label={r.tag}
              net={r.net_pnl}
              maxAbs={maxAbs}
              capitalize
              right={
                <>
                  {formatDollarSigned(r.net_pnl)}
                  <span className="text-fg-tertiary-2"> · {r.trades}t</span>
                </>
              }
            />
          ))}
        </div>
      )}
    </Panel>
  );
}

/** A centered-zero horizontal meter — bull fills right, bear fills left. */
function MeterRow({
  label,
  net,
  maxAbs,
  right,
  capitalize,
}: {
  label: string;
  net: number;
  maxAbs: number;
  right: React.ReactNode;
  capitalize?: boolean;
}) {
  const w = (Math.abs(net) / maxAbs) * 48; // up to 48% from center
  const bull = net >= 0;
  return (
    <div className="grid items-center gap-2 tabular-nums" style={{ gridTemplateColumns: "96px 1fr 96px" }}>
      <span className={`text-tiny text-fg-secondary truncate ${capitalize ? "capitalize" : ""}`} style={{ fontSize: 11 }}>
        {label}
      </span>
      <span className="relative bg-tier-0 border border-hairline" style={{ height: 8 }}>
        <span className="absolute bg-hairline-strong" style={{ left: "50%", top: -2, bottom: -2, width: 1 }} />
        <span
          className={`absolute top-0 bottom-0 ${bull ? "bg-bullish" : "bg-bearish"}`}
          style={bull ? { left: "50%", width: `${w}%` } : { right: "50%", width: `${w}%` }}
        />
      </span>
      <span className={`text-tiny text-right ${pnlClass(net)}`} style={{ fontSize: 11 }}>
        {right}
      </span>
    </div>
  );
}

// -- panel chrome ------------------------------------------------------------

function Panel({ children }: { children: React.ReactNode }) {
  return <section className="flex flex-col bg-tier-1 border border-hairline">{children}</section>;
}

function PanelHead({ k, r }: { k: string; r?: string }) {
  return (
    <div
      className="flex items-center justify-between px-3 border-b border-hairline shrink-0"
      style={{ height: 28 }}
    >
      <span className="uppercase tracking-label-up text-fg-secondary" style={{ fontSize: 10 }}>
        {k}
      </span>
      {r && (
        <span className="uppercase tracking-label-up text-fg-tertiary tabular-nums" style={{ fontSize: 9 }}>
          {r}
        </span>
      )}
    </div>
  );
}

function Empty({ label }: { label: string }) {
  return <div className="px-3 py-6 text-tiny text-fg-tertiary text-center">{label}</div>;
}

function LoadingState() {
  return <div className="p-3 text-tiny text-fg-tertiary">Loading analytics…</div>;
}

function ErrorState({ message }: { message: string }) {
  return <div className="p-3 text-tiny text-bearish">{message}</div>;
}

// -- range → date window -----------------------------------------------------

function rangeToDates(range: Range): { since: string | null; until: string | null } {
  if (range === "All") return { since: null, until: null };
  const now = new Date();
  const today = localIso(now);
  if (range === "Today") return { since: today, until: today };
  if (range === "Month") {
    const first = new Date(now.getFullYear(), now.getMonth(), 1);
    return { since: localIso(first), until: null };
  }
  // Week — Monday of the current week through today.
  const dow = (now.getDay() + 6) % 7; // 0 = Monday
  const monday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - dow);
  return { since: localIso(monday), until: null };
}

function localIso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// -- formatting --------------------------------------------------------------

function toneClass(tone: "bull" | "bear"): string {
  return tone === "bull" ? "text-bullish" : "text-bearish";
}

function pnlClass(v: number | null): string {
  if (v == null) return "text-fg-tertiary";
  if (v > 0) return "text-bullish";
  if (v < 0) return "text-bearish";
  return "text-fg-secondary";
}

function formatDollar(value: number): string {
  if (!Number.isFinite(value)) return "—";
  const sign = value < 0 ? "−" : "";
  return `${sign}$${Math.abs(value).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

function formatDollarSigned(value: number): string {
  if (!Number.isFinite(value)) return "—";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}$${Math.abs(value).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

function formatR(r: number): string {
  const sign = r > 0 ? "+" : r < 0 ? "−" : "";
  return `${sign}${Math.abs(r).toFixed(2)}R`;
}
