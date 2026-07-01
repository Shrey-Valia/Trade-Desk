import { useMemo } from "react";
import { Link } from "react-router-dom";

import { EquityCurveSvg } from "@/components/analytics/EquityCurveSvg";
import { GaugeDial } from "@/components/analytics/GaugeDial";
import { CombineCardsGrid } from "@/components/combines/CombineCards";
import { CombineSwitcher } from "@/components/combines/CombineSwitcher";
import { PageHeader } from "@/components/layout/PageHeader";
import { colors } from "@/lib/design";
import { EmptyState } from "@/components/ui/EmptyState";
import { LoadError } from "@/components/ui/LoadError";
import { MetricPill } from "@/components/ui/MetricPill";
import { useAccountState } from "@/hooks/useAccountState";
import { useActivateAccount, useCombines } from "@/hooks/useCombines";
import { useJournalAnalytics } from "@/hooks/useJournalAnalytics";
import type { CombineOut } from "@/types/combine";

/**
 * /dashboard — the prop-firm management home (Topstep-style).
 *
 * Top: active-combine summary pills + Start a Trading Combine CTA.
 * Middle: account balance over time (closed-trade equity offset to
 * absolute balance) + performance tracker, with the Path to Funding
 * objectives rail on the right. Bottom: every owned combine as a
 * managed card (activate / rename / archive).
 *
 * Everything here is display + management; rule numbers come from the
 * same computed account-state/combines payloads the terminal header
 * uses. Objectives are display-only — nothing settles a combine yet.
 */
export function DashboardPage() {
  const combines = useCombines();
  const hasAny = (combines.data?.combines.length ?? 0) > 0;

  return (
    <div className="flex flex-col h-full min-h-0 bg-tier-0">
      <PageHeader
        title="Dashboard"
        subtitle={
          combines.data
            ? `${combines.data.slots_used} of ${combines.data.slots_total} combine slots used`
            : undefined
        }
      />
      <main className="flex-1 min-h-0 overflow-y-auto border-t border-hairline">
        {combines.isPending ? (
          <div className="px-4 py-6 text-tiny text-fg-tertiary-2">
            Loading combines…
          </div>
        ) : combines.isError ? (
          <LoadError subject="your combines" onRetry={combines.refetch} />
        ) : !hasAny ? (
          <FirstCombineHero />
        ) : (
          <DashboardBody />
        )}
      </main>
    </div>
  );
}

function FirstCombineHero() {
  return (
    <div className="h-full flex flex-col items-center justify-center gap-3 px-6 text-center">
      <span
        className="uppercase tracking-label-up text-fg-secondary"
        style={{ fontSize: 11, letterSpacing: "0.08em" }}
      >
        No combines yet
      </span>
      <span className="text-display font-medium text-fg-primary">
        Start your first Trading Combine.
      </span>
      <span className="text-tiny text-fg-tertiary max-w-md leading-relaxed">
        Pick an account size, trade 0DTE options within the loss limits, and
        work toward the profit target. Your dashboard tracks every rule live.
      </span>
      <Link
        to="/combines/new"
        className="mt-2 h-9 px-4 inline-flex items-center uppercase tracking-label-up bg-amber text-tier-0 hover:opacity-90 font-medium"
        style={{ fontSize: 12, borderRadius: 0 }}
      >
        Start a Trading Combine →
      </Link>
    </div>
  );
}

function DashboardBody() {
  const { data: account } = useAccountState();
  const activeCombineId = account?.combine_id ?? null;
  const analytics = useJournalAnalytics(
    activeCombineId != null ? { combineId: activeCombineId } : {},
  );
  // Until there's at least one closed trade, the three analytics panels are
  // empty voids — show one purposeful "get started" card instead.
  const hasTrades = (analytics.data?.kpis?.closed_trades ?? 0) > 0;
  const showPanels = hasTrades || analytics.isPending;

  return (
    <div className="p-3.5 flex flex-col gap-3.5">
      <ActivationBanner />
      {/* Top strip: account switcher + active combine identity + CTAs */}
      <div className="flex items-center gap-3 flex-wrap">
        <CombineSwitcher />
        {account && (
          <>
            <MetricPill label="BAL" value={formatDollar(account.balance)} />
            <MetricPill
              label="CLOSED P&L"
              value={formatSigned(account.realized_pnl)}
              signed={account.realized_pnl}
            />
            <MetricPill label="MLL" value={formatDollar(account.mll)} />
            <MetricPill
              label="DLL"
              value={`${formatDollar(account.dll_used)} / ${formatDollar(account.dll_budget)}`}
              tone={account.dll_breached ? "bearish" : "default"}
            />
          </>
        )}
        <div className="ml-auto flex items-center gap-2">
          <Link
            to="/positions"
            className="h-8 px-3 inline-flex items-center text-tiny uppercase tracking-label-up border border-hairline text-fg-secondary hover:bg-tier-2 hover:text-fg-primary"
            style={{ borderRadius: 0 }}
          >
            Launch terminal →
          </Link>
          <Link
            to="/combines/new"
            className="h-8 px-3 inline-flex items-center text-tiny uppercase tracking-label-up bg-amber text-tier-0 hover:opacity-90 font-medium"
            style={{ borderRadius: 0 }}
          >
            Start a Trading Combine
          </Link>
        </div>
      </div>

      {/* Middle: balance curve + perf | path to funding */}
      <div className="grid gap-3.5 items-start grid-cols-1 lg:grid-cols-[2fr_1fr]">
        <div className="flex flex-col gap-3.5 min-w-0">
          {showPanels ? (
            <>
              <BalancePanel
                startingBalance={account?.starting_balance ?? 0}
                combineName={account?.combine_name}
                analytics={analytics}
                mll={account?.mll}
                profitTargetBalance={
                  account
                    ? account.starting_balance + (account.profit_target ?? 0)
                    : undefined
                }
              />
              <PerformancePanel analytics={analytics} />
              <TradesByDurationPanel analytics={analytics} />
            </>
          ) : (
            <Panel title="Your combine at a glance" right={account?.combine_name ?? ""}>
              <EmptyState
                title="No closed trades yet"
                body="Open your first 0DTE position from the terminal. Your balance curve, performance tracker, and trade-by-duration breakdown fill in automatically as you close trades."
                action={
                  <>
                    <Link
                      to="/positions"
                      className="h-9 px-4 inline-flex items-center uppercase tracking-label-up bg-amber text-tier-0 hover:opacity-90 rounded-btn font-medium"
                      style={{ fontSize: 12 }}
                    >
                      Launch terminal →
                    </Link>
                    <Link
                      to="/journal"
                      className="h-9 px-4 inline-flex items-center uppercase tracking-label-up border border-hairline-strong text-fg-secondary hover:bg-tier-2 hover:text-fg-primary rounded-btn"
                      style={{ fontSize: 12 }}
                    >
                      Log a trade
                    </Link>
                  </>
                }
              />
            </Panel>
          )}
        </div>
        <PathToFunding />
      </div>

      <CombineCards />
    </div>
  );
}

// -- funded → activate ---------------------------------------------------------

/**
 * Prominent prompt for the pass→funded phase: any funded combine that hasn't
 * been activated yet shows an Activate button. One unified flow — the fee is
 * $149 on the activation path and $0 ("free") on no-activation — that unlocks
 * payouts. Hidden when there's nothing to activate.
 */
function ActivationBanner() {
  const { data } = useCombines();
  const pending = (data?.combines ?? []).filter(
    (c) => c.funded && c.activation_required && c.status !== "archived",
  );
  if (pending.length === 0) return null;

  return (
    <div className="border border-amber bg-tier-1" style={{ borderRadius: 4 }}>
      <div className="px-3.5 py-2.5 border-b border-hairline flex items-baseline gap-2">
        <span className="text-amber font-medium" style={{ fontSize: 13 }}>
          Evaluation passed — activate your funded account
        </span>
        <span className="text-tiny text-fg-tertiary-2">
          Activation unlocks payouts.
        </span>
      </div>
      <div className="flex flex-col">
        {pending.map((c) => (
          <ActivationRow key={c.id} combine={c} />
        ))}
      </div>
    </div>
  );
}

function ActivationRow({ combine }: { combine: CombineOut }) {
  const activate = useActivateAccount();
  const free = combine.activation_fee <= 0;
  return (
    <div className="px-3.5 py-2 flex items-center gap-3 border-t border-hairline first:border-t-0">
      <div className="min-w-0 flex-1">
        <span className="text-fg-primary font-medium truncate" style={{ fontSize: 13 }}>
          {combine.name}
        </span>
        <span className="text-fg-tertiary-2 tabular-nums ml-2" style={{ fontSize: 12 }}>
          {combine.tier} · {combine.account_code}
        </span>
      </div>
      <span className="text-tiny text-fg-secondary tabular-nums shrink-0">
        {free ? "No activation fee" : `Activation fee $${combine.activation_fee}`}
      </span>
      <button
        type="button"
        disabled={activate.isPending}
        onClick={() => activate.mutate(combine.id)}
        className="h-8 px-3 text-tiny uppercase tracking-label-up bg-amber text-tier-0 hover:opacity-90 disabled:opacity-50 shrink-0 rounded-btn font-medium"
      >
        {activate.isPending ? "…" : free ? "Activate (free)" : `Activate — $${combine.activation_fee}`}
      </button>
    </div>
  );
}

// -- balance over time ---------------------------------------------------------

function BalancePanel({
  startingBalance,
  combineName,
  analytics,
  mll,
  profitTargetBalance,
}: {
  startingBalance: number;
  combineName: string | undefined;
  analytics: ReturnType<typeof useJournalAnalytics>;
  mll: number | undefined;
  profitTargetBalance: number | undefined;
}) {
  const equity = analytics.data?.equity;
  // The equity curve is cumulative closed P&L; offset by the combine's
  // starting balance so the chart reads as account balance.
  const points = useMemo(
    () =>
      (equity?.points ?? []).map((p) => ({
        date: p.date,
        cumulative_pnl: startingBalance + p.cumulative_pnl,
      })),
    [equity, startingBalance],
  );

  return (
    <Panel
      title="Account balance over time"
      right={combineName ? `${combineName} · closed trades` : ""}
    >
      {points.length >= 2 ? (
        <div style={{ height: 220 }}>
          <EquityCurveSvg
            points={points}
            drawdownPeakDate={equity?.drawdown_peak_date}
            drawdownTroughDate={equity?.drawdown_trough_date}
            baseline={startingBalance}
            mll={mll}
            profitTarget={profitTargetBalance}
          />
        </div>
      ) : analytics.isPending ? (
        <div
          className="flex items-center justify-center text-tiny text-fg-tertiary-2"
          style={{ height: 120 }}
        >
          Loading…
        </div>
      ) : (
        <EmptyState
          compact
          title="Balance curve pending"
          body="The curve appears once you've closed at least two trades on this combine."
        />
      )}
    </Panel>
  );
}

// -- performance tracker --------------------------------------------------------

function PerformancePanel({
  analytics,
}: {
  analytics: ReturnType<typeof useJournalAnalytics>;
}) {
  const k = analytics.data?.kpis;
  const win = k?.win_rate ?? null;
  const avgWin = k?.avg_winner ?? null;
  const avgLoss = k?.avg_loser != null ? Math.abs(k.avg_loser) : null;
  // Avg-win / avg-loss gauges fill by their share of the win/loss balance
  // (a meaningful, bounded visual); the center value is the real dollar
  // figure. With only one side present, that side fills fully.
  const denom = (avgWin ?? 0) + (avgLoss ?? 0);
  const winShare =
    avgWin == null ? null : denom > 0 ? avgWin / denom : 1;
  const lossShare =
    avgLoss == null ? null : denom > 0 ? avgLoss / denom : 1;

  return (
    <Panel title="Performance tracker" right="closed trades on this combine">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <GaugeDial
          label="Win rate"
          value={win != null ? `${Math.round(win * 100)}%` : "—"}
          fraction={win}
          color={colors.accentAmber}
          sub={k ? `${k.closed_trades} closed` : undefined}
        />
        <GaugeDial
          label="Avg winning trade"
          value={avgWin != null ? formatDollar(avgWin) : "—"}
          fraction={winShare}
          color={colors.bullish}
        />
        <GaugeDial
          label="Avg losing trade"
          value={avgLoss != null ? formatDollar(avgLoss) : "—"}
          fraction={lossShare}
          color={colors.bearish}
        />
      </div>
      <div className="mt-3 pt-3 border-t border-hairline text-center text-tiny text-fg-tertiary-2 tabular-nums">
        Avg hold {k?.avg_hold_min != null ? formatMinutes(k.avg_hold_min) : "—"}
      </div>
    </Panel>
  );
}

// -- trades by duration ----------------------------------------------------------

function TradesByDurationPanel({
  analytics,
}: {
  analytics: ReturnType<typeof useJournalAnalytics>;
}) {
  const buckets = analytics.data?.by_hold_duration ?? [];
  const maxTrades = Math.max(1, ...buckets.map((b) => b.trades));
  const anyTrades = buckets.some((b) => b.trades > 0);

  return (
    <Panel title="Successful trades by duration" right="closed trades · by hold time">
      {anyTrades ? (
        <div className="flex flex-col gap-2">
          {buckets.map((b) => {
            const pct = (b.trades / maxTrades) * 100;
            const barCls =
              b.net_pnl > 0
                ? "bg-bullish"
                : b.net_pnl < 0
                  ? "bg-bearish"
                  : "bg-tier-3";
            return (
              <div key={b.label} className="flex items-center gap-2">
                <span
                  className="text-tiny tabular-nums text-fg-tertiary-2 text-right shrink-0"
                  style={{ width: 56 }}
                >
                  {b.label}
                </span>
                <div className="flex-1 h-3 bg-tier-2 relative min-w-0">
                  <div
                    className={`absolute inset-y-0 left-0 ${barCls}`}
                    style={{ width: `${pct}%`, opacity: 0.85 }}
                  />
                </div>
                <span
                  className="text-tiny tabular-nums text-fg-secondary text-right shrink-0"
                  style={{ width: 96 }}
                >
                  {b.trades} {b.trades === 1 ? "trade" : "trades"}
                  {b.win_rate != null && (
                    <span className="text-fg-tertiary-2">
                      {" "}
                      · {Math.round(b.win_rate * 100)}%
                    </span>
                  )}
                </span>
              </div>
            );
          })}
          <span className="text-tiny text-fg-tertiary-2">
            Bar length = trade count; green = net-winning bucket, red =
            net-losing. % is the bucket win rate.
          </span>
        </div>
      ) : (
        <EmptyState
          compact
          title="No timed trades yet"
          body="Duration buckets appear once you close intraday trades."
        />
      )}
    </Panel>
  );
}

// -- path to funding -------------------------------------------------------------

function PathToFunding() {
  const { data: account } = useAccountState();
  if (!account) return null;
  const target = account.profit_target ?? 0;
  const progress = account.objective_progress ?? 0;
  const cushion = account.balance - account.mll;
  const dllRemaining = Math.max(0, account.dll_budget - account.dll_used);
  const totalProfit = account.realized_pnl;
  const largestDayPct =
    totalProfit > 0 ? (account.largest_day_profit / totalProfit) * 100 : 0;
  const daysFraction =
    account.min_trading_days > 0
      ? account.days_traded / account.min_trading_days
      : 0;

  return (
    <Panel title="Path to funding" right={account.account_code ?? ""}>
      <div className="flex flex-col gap-3">
        {/* Objective: profit target */}
        <div className="flex flex-col gap-1">
          <div className="flex items-baseline justify-between">
            <span
              className="uppercase tracking-label-up text-fg-secondary"
              style={{ fontSize: 12 }}
            >
              Profit target
            </span>
            <span className="text-tiny tabular-nums text-fg-secondary">
              {formatSigned(account.realized_pnl)} / ${target.toLocaleString()}
            </span>
          </div>
          <ProgressBar
            fraction={progress}
            tone={progress >= 1 ? "bullish" : "amber"}
          />
          <span className="text-tiny text-fg-tertiary-2">
            {progress >= 1
              ? "Target reached — evaluation review is a manual step for now."
              : `${Math.round(progress * 100)}% of the way there.`}
          </span>
        </div>

        <div className="border-t border-hairline" />

        <RuleRow
          label="Maximum loss limit"
          value={formatDollar(account.mll)}
          status={
            account.balance < account.mll
              ? { text: "BREACHED", tone: "bearish" }
              : {
                  text: `$${Math.round(cushion).toLocaleString()} cushion`,
                  tone: "ok",
                }
          }
          hint="Trails your high-water mark; capped at the starting balance."
        />
        <RuleRow
          label="Daily loss limit"
          value={`${formatDollar(dllRemaining)} left today`}
          status={
            account.dll_breached
              ? { text: "HIT TODAY", tone: "bearish" }
              : { text: "ok", tone: "ok" }
          }
          hint="Enforced — new opens are blocked once realized losses hit it; resets at the 5pm-PT settlement."
        />
        <RuleRow
          label="Consistency target"
          value={
            totalProfit > 0
              ? `Largest day is ${Math.round(largestDayPct)}% of total profit`
              : "No realized profit yet"
          }
          status={
            account.consistency_ok
              ? { text: "ok", tone: "ok" }
              : { text: "EXCEEDS 50%", tone: "bearish" }
          }
          hint="No single trading day may exceed 50% of total realized profit."
        />

        {/* Min trading days — a pass requirement alongside the target. */}
        <div className="flex flex-col gap-1">
          <div className="flex items-baseline justify-between">
            <span
              className="uppercase tracking-label-up text-fg-secondary"
              style={{ fontSize: 12 }}
            >
              Trading days
            </span>
            <span className="text-tiny tabular-nums text-fg-secondary">
              {account.days_traded} / {account.min_trading_days}
            </span>
          </div>
          <ProgressBar
            fraction={daysFraction}
            tone={
              account.days_traded >= account.min_trading_days
                ? "bullish"
                : "amber"
            }
          />
          <span className="text-tiny text-fg-tertiary-2">
            Minimum distinct trading days required to pass.
          </span>
        </div>

        <div className="border-t border-hairline" />
        <span className="text-tiny text-fg-tertiary leading-relaxed">
          Profit target, consistency, and min trading days are the pass
          conditions the combine engine evaluates; the MLL/DLL floors are
          the same numbers as the terminal header. Funding payout is still a
          manual step.
        </span>
      </div>
    </Panel>
  );
}

function RuleRow({
  label,
  value,
  status,
  hint,
}: {
  label: string;
  value: string;
  status: { text: string; tone: "ok" | "bearish" };
  hint: string;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-baseline justify-between gap-2">
        <span
          className="uppercase tracking-label-up text-fg-secondary"
          style={{ fontSize: 12 }}
        >
          {label}
        </span>
        <span
          className={`text-tiny uppercase tracking-label-up ${
            status.tone === "bearish" ? "text-bearish" : "text-bullish"
          }`}
          style={{ fontSize: 11 }}
        >
          {status.text}
        </span>
      </div>
      <span className="text-tiny tabular-nums text-fg-primary">{value}</span>
      <span className="text-tiny text-fg-tertiary-2" style={{ fontSize: 12 }}>
        {hint}
      </span>
    </div>
  );
}

function ProgressBar({
  fraction,
  tone,
}: {
  fraction: number;
  tone: "amber" | "bullish";
}) {
  const pct = Math.max(0, Math.min(1, fraction)) * 100;
  return (
    <div
      className="h-1.5 bg-tier-2 relative"
      role="progressbar"
      aria-valuenow={Math.round(pct)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className={`absolute inset-y-0 left-0 ${tone === "bullish" ? "bg-bullish" : "bg-amber"}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

// -- combine cards -----------------------------------------------------------------

function CombineCards() {
  const { data } = useCombines();
  const combines = data?.combines ?? [];
  if (combines.length === 0) return null;
  return (
    <Panel
      title="Your combines"
      right={`${data?.slots_used ?? 0} of ${data?.slots_total ?? 5} slots used`}
    >
      <CombineCardsGrid
        combines={combines}
        activeCombineId={data?.active_combine_id}
        leadCombineId={data?.copy_lead_combine_id}
      />
    </Panel>
  );
}

// -- shared -------------------------------------------------------------------

function Panel({
  title,
  right,
  children,
}: {
  title: string;
  right?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className="border border-hairline-strong bg-tier-1"
      style={{ borderRadius: 4 }}
    >
      <div className="flex items-baseline justify-between px-3 py-1.5 border-b border-hairline">
        <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
          {title}
        </span>
        {right && (
          <span
            className="uppercase tracking-label-up text-fg-tertiary-2 tabular-nums"
            style={{ fontSize: 11 }}
          >
            {right}
          </span>
        )}
      </div>
      <div className="px-3 py-2.5">{children}</div>
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

function formatSigned(v: number): string {
  if (!Number.isFinite(v)) return "$0.00";
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  return `${sign}$${Math.abs(v).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function formatMinutes(min: number): string {
  if (min < 60) return `${Math.round(min)}m`;
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  return `${h}h ${m}m`;
}
